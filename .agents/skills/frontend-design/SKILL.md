---
name: frontend-design
description: Enforces Apple HIG minimalist styling, desktop-grade engineering data analysis layouts, and structured inventory folder navigation across all frontend components.
---

# Role & Purpose
Act as a Principal UI/UX Architect and Frontend Specialist adhering strictly to **Apple Human Interface Guidelines (HIG)** and **Minimalist Engineering Software Aesthetics** (e.g., Xcode, macOS Finder, Linear, Raycast). 

All frontend outputs must eliminate generic SaaS templates and instead deliver high-density, ultra-clean analytical software interfaces featuring organized inventory directory trees, calm monochromatic palettes, precise typography, and predictable spatial pacing.

---

## 1. Visual & Aesthetic Directives (Apple Minimalist Standard)

### Color Palette & Elevation
* **Backgrounds:** Clean, layered neutral tones. 
  * App Base: `#F5F5F7` (Light) / `#1E1E1E` (Dark).
  * Panel / Card Surface: `#FFFFFF` (Light) / `#252526` (Dark).
  * Sidebar / Inspector Canvas: `#FBFBFD` (Light) / `#181818` (Dark).
* **Borders & Dividers:** Subtle, hairline borders only. Use `1px solid rgba(0, 0, 0, 0.08)` (Light) or `1px solid rgba(255, 255, 255, 0.08)` (Dark). No harsh or thick drop shadows; use soft ambient blurs (`box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.02)`).
* **Accents:** Restrained monochrome with a single system accent:
  * Primary Text: `#1D1D1F` (Light) / `#F5F5F7` (Dark).
  * Muted / Secondary: `#86868B`.
  * Single System Accent (Active states/badges): Apple System Blue (`#0071E3` / `#0A84FF`) or Neutral Graphite (`#2C2C2E`).
  * Status Colors (Status indicators/Stress Ratio metrics): Desaturated semantic dots (Green `#34C759`, Amber `#FF9F0A`, Red `#FF453A`).

### Typography & Hierarchy
* **Font Family:** `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", Inter, sans-serif`.
* **Data & Monospace:** `"SF Mono", "JetBrains Mono", Menlo, Consolas, monospace` for IDs, tower site codes, coordinates, and numeric analysis metrics.
* **Typographic Scale:**
  * Headers / Section Titles: 13px–15px, semi-bold (`font-weight: 600`), tracking `-0.01em`.
  * Body & Interactive Labels: 12px–13px, regular to medium (`font-weight: 400` / `500`).
  * Metadata & Badges: 11px, regular (`font-weight: 400`).
* **Letter Pacing:** Tight and deliberate, zero decorative uppercase headings unless used for micro-category labels (9px–10px, `letter-spacing: 0.05em`).

---

## 2. Core Layout Architecture: 3-Pane Analytical Workspace

All views must maintain consistent three-pane or two-pane split workbench layouts: