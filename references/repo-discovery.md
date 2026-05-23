# Repository Discovery

The skill supports mixed repositories and uses discovery heuristics before a curated bundle exists.

## Supported Layouts

- Maven multi-module repositories
- Python monorepos with `app/`, `services/`, `api/`, or `frontend/`
- Node or TypeScript packages with `package.json`
- mixed repositories combining the above

## Maven Heuristics

- read root `pom.xml`
- collect `<modules>`
- classify modules by name:
  - `security`, `billing`, `entitlement`, `tenant`, `audit` -> `shared-capability`
  - `gateway`, `ops`, `deployment` -> `infra`
  - `sdk-*` -> `adapter`
  - `admin-ui`, `frontend` -> `ui`
  - `demo`, `app` -> `feature-module`

## Python Heuristics

- treat `app/api` as `adapter`
- treat `app/database` as `infra`
- treat `app/agents` and `app/models` as domain or shared runtime layers
- treat service files or folders containing `workflow`, `outline`, `lore`, `character`, `skill`, or `context` as capability candidates

## Node and TypeScript Heuristics

- use `package.json` to detect packages
- prefer `src/index.ts` or package `exports` as public entry candidates
- treat `frontend`, `admin-ui`, and browser packages as `ui`
- treat `sdk` packages as `adapter`

## Discovery Limitations

- discovery cannot replace actual domain knowledge
- public API semantics still need curation
- capability ownership still needs named owners

Use discovery for the first pass, not as the final architecture contract.
