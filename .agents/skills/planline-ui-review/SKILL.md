---
name: planline-ui-review
description: Review, design and improve Planline's UI, CSS, responsive layouts, navigation, documentation reader, accessibility and visual consistency.
---

# Planline UI Review

Use this skill whenever a change affects the Planline browser or desktop UI, documentation pages, CSS, HTML, navigation, forms, controls, layout, or visual presentation.

## Product constraints

- Planline is a local-first 2D floor-plan digitising and drawing-review application. Do not imply automatic CAD reconstruction is already available.
- Preserve the current product workflows and data semantics. Do not invent functionality to make a screen look fuller.
- Treat the dashboard, Drawing, OCR Studio, Settings, Documentation and Architecture as one application, not independent microsites.
- Use the shared design tokens in `web/styles.css`. Avoid page-specific hard-coded colours, typography, shadows, spacing systems or new global overrides.
- Keep dark mode as the default while respecting the user's saved theme preference.
- Prioritise readable labels and task clarity over dense metadata, decorative cards, gradients or excessive iconography.

## Required review workflow

1. Read the relevant HTML/template, CSS, JavaScript and existing browser tests before editing.
2. If the official UI/UX Pro Max skill is installed at `.agents/skills/ui-ux-pro-max/`, use its design-system search for product-wide changes and targeted `ux`, `typography` or `color` searches for focused problems. Example:
   ```bash
   python .agents/skills/ui-ux-pro-max/scripts/search.py "desktop floorplan drafting application" --design-system -p "Planline"
   python .agents/skills/ui-ux-pro-max/scripts/search.py "responsive navigation no horizontal overflow" --domain ux
   ```
3. Keep the global shell consistent: same brand mark, header, primary navigation, active state, theme control, spacing and focus treatment on every page, including generated documentation pages.
4. Check responsive widths of 320, 360, 390, 520, 760, 900, 1024, 1280 and 1440 pixels. There must be no accidental horizontal page scrolling, clipped controls, overlapping navigation or unreadable wrapping.
5. Keep interactive targets at least 44px where practical; retain visible keyboard focus, semantic labels, keyboard operation and reduced-motion support.
6. Check text contrast, line length, hierarchy and font size. Normal body text should generally be 15–16px or larger; do not shrink essential labels to fit a layout.
7. Use Playwright browser tests and screenshots to inspect actual rendered pages. A passing CSS string assertion is not a visual test.
8. Fix the underlying layout/component rule instead of appending another one-off override. If a shared rule changes, verify all pages that consume it.
9. Add or update a regression test for every repaired layout or interaction bug.

## Review checklist

- [ ] All pages share the same header, navigation, theme control and design tokens.
- [ ] Documentation looks like a Planline workspace, not a separate documentation theme.
- [ ] No horizontal overflow at the required viewport widths.
- [ ] Navigation works with touch, mouse and keyboard.
- [ ] Main content has clear hierarchy and an obvious next action.
- [ ] Text is readable at normal zoom and mobile sizes.
- [ ] Focus indicators and contrast remain visible in both themes.
- [ ] Tables and code blocks scroll within their own containers, not the whole page.
- [ ] Browser tests cover the behaviour, not just the presence of CSS selectors.

## Do not

- Add a second stylesheet or a new independent token system for Documentation.
- Fix overflow by hiding arbitrary content or setting the whole page to a fixed width.
- add `!important` overrides unless there is a documented, unavoidable cascade reason.
- Replace meaningful controls with decorative icons or placeholder links.
- Claim a visual fix is verified without running the browser checks.
