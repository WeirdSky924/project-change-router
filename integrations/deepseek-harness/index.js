import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const PROVIDER_NAME = 'project-change-router-skill'
const BUNDLED_SKILL_RANK = 600
const SKILL_URL = new URL('../../SKILL.md', import.meta.url)
const SKILL_PATH = fileURLToPath(SKILL_URL)
const RESOURCE_BASE = {
  kind: 'directory',
  path: fileURLToPath(new URL('../../', import.meta.url)),
}
const INVOCATION = { modelInvocable: true, userInvocable: true }

function decodeScalar(value) {
  const scalar = value.trim()
  if (scalar.startsWith('"')) return JSON.parse(scalar)
  if (scalar.startsWith("'") && scalar.endsWith("'")) {
    return scalar.slice(1, -1).replaceAll("''", "'")
  }
  return scalar
}

function foldedBlock(lines) {
  const content = lines.map(line => line.trim())
  const paragraphs = []
  let current = []
  for (const line of content) {
    if (line.length === 0) {
      if (current.length > 0) paragraphs.push(current.join(' '))
      current = []
    } else {
      current.push(line)
    }
  }
  if (current.length > 0) paragraphs.push(current.join(' '))
  return paragraphs.join('\n')
}

function frontmatterField(frontmatter, key) {
  const lines = frontmatter.split(/\r?\n/)
  const pattern = new RegExp(`^${key}:\\s*(.*)$`)
  for (let index = 0; index < lines.length; index += 1) {
    const match = pattern.exec(lines[index])
    if (match === null) continue
    const value = match[1]
    if (!value.startsWith('>') && !value.startsWith('|')) return decodeScalar(value)

    const block = []
    for (let next = index + 1; next < lines.length; next += 1) {
      const line = lines[next]
      if (line.length > 0 && !/^\s/.test(line)) break
      block.push(line)
    }
    return value.startsWith('>') ? foldedBlock(block) : block.map(line => line.trim()).join('\n').trim()
  }
  return undefined
}

function parseSkillMarkdown(raw) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/.exec(raw)
  if (match === null) throw new Error('SKILL.md requires YAML frontmatter')
  const name = frontmatterField(match[1], 'name')
  const description = frontmatterField(match[1], 'description')
  if (typeof name !== 'string' || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) {
    throw new Error('SKILL.md contains an invalid skill name')
  }
  if (typeof description !== 'string' || description.length === 0) {
    throw new Error('SKILL.md requires a description')
  }
  return { name, description, content: match[2].trim() }
}

async function loadSkill(signal) {
  const raw = await readFile(SKILL_URL, { encoding: 'utf8', signal })
  return parseSkillMarkdown(raw)
}

const provider = {
  name: PROVIDER_NAME,
  async list(options = {}) {
    const skill = await loadSkill(options.signal)
    return [{
      name: skill.name,
      description: skill.description,
      invocation: INVOCATION,
      provider: PROVIDER_NAME,
      source: 'bundled',
      resourceBase: RESOURCE_BASE,
      rank: BUNDLED_SKILL_RANK,
      locator: SKILL_PATH,
      path: SKILL_PATH,
    }]
  },
  async get(candidate, options = {}) {
    const skill = await loadSkill(options.signal)
    if (candidate.name !== skill.name) return undefined
    return {
      name: skill.name,
      description: skill.description,
      invocation: INVOCATION,
      provider: PROVIDER_NAME,
      source: 'bundled',
      resourceBase: RESOURCE_BASE,
      content: skill.content,
      path: SKILL_PATH,
    }
  },
}

export const name = PROVIDER_NAME
export const inject = ['skills']

export function apply(ctx) {
  ctx.skills.registerProvider(() => provider)
}
