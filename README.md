# BlazeFit Project Dashboard

Public GitHub Pages site: https://blazefit.github.io/project-dashboard/

## Security / privacy invariant

This repository is **public**. `index.html` must list **public repos only**.
Never publish private repo names, descriptions, or URLs.

`generate.py` enforces that at generation time (`gh repo list --visibility public`
plus an `isPrivate` hard filter). Do not remove that filter.

## Monday refresh

- **Durable path (preferred):** `.github/workflows/monday-refresh.yml` runs Mondays ~7 AM ET and regenerates `index.html` from public repos only.
- **Legacy path:** An untracked `generate.py` historically lived on the Hermes host `daneelbrain` at `~/hermes/project-dashboard/` and was invoked by a Monday 7 AM ET cron that committed as `BlazeFit <blazefit@crossfitblaze.com>`. That copy did **not** filter private repos (leak 2026-09-28). When daneelbrain is back, replace its `generate.py` with this repo's hardened copy or disable that cron so only the Actions workflow publishes.

## Manual refresh

```bash
DASHBOARD_SKIP_PUSH=1 python3 generate.py   # write index.html only
python3 generate.py                         # write + commit + push (needs git remote auth)
```
