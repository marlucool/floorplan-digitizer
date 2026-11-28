# Planline UI/UX workflow

Planline includes a repository-level UI review skill and an automated design-guidance job.

## Repository skill

`.agents/skills/planline-ui-review/SKILL.md` contains the Planline-specific review rules. Compatible coding agents that support Agent Skills can load it directly from the repository.

## UI/UX Pro Max design intelligence

The upstream [UI/UX Pro Max skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) provides searchable design-system, product, typography, color and UX guidance. Install its current pinned CLI output into this repository with:

- Linux/macOS: `bash scripts/setup_ui_ux_skill.sh`
- Windows PowerShell: `./scripts/setup_ui_ux_skill.ps1`

The setup scripts install version 2.15.0 into `.agents/skills/ui-ux-pro-max/`. Review generated files and commit them if you want the complete searchable skill checked into the repository. The Planline-specific skill remains available even when the upstream skill has not been installed.

Useful searches:

```bash
python .agents/skills/ui-ux-pro-max/scripts/search.py "desktop floorplan drafting application" --design-system -p "Planline"
python .agents/skills/ui-ux-pro-max/scripts/search.py "responsive navigation no horizontal overflow" --domain ux
python .agents/skills/ui-ux-pro-max/scripts/search.py "readable technical dashboard typography" --domain typography
```

## Automated review

The **UI/UX suggestions** GitHub Actions workflow runs for changes to UI, documentation and the review skill. It publishes design-system and responsive-UX recommendations in the Actions job summary.

The existing Playwright browser suite is the enforcement layer: it checks rendered pages and responsive navigation. Recommendations are advisory; browser regressions should be fixed before merging.

## Design principles for Planline

- One coherent app shell and shared design tokens across Dashboard, Drawing, OCR Studio, Settings and Documentation.
- Clear next actions; avoid overloading screens with explanatory text or tiny labels.
- Dark mode by default, with a working saved preference.
- Responsive navigation with a real mobile menu, not a squeezed row of links.
- No page-level horizontal overflow. Long tables and code blocks may scroll inside their own containers.
- Accessible contrast, visible focus, semantic controls and reduced-motion support.
