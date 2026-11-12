---
name: XJTLU PaperForge
description: A quiet local archive desk with a warm, expressive forest companion.
colors:
  cream: '#f5f3e9'
  paper: '#fffef9'
  forest: '#234c3c'
  forest-hover: '#193c2f'
  ink: '#263d32'
  muted: '#647063'
  sage: '#dfe7d7'
  meadow: '#edf0e5'
  line: '#dce0d3'
  rust: '#9d4b34'
  error-surface: '#f9ece4'
  focus-ring: '#638366'
  selected-border: '#52765b'
  selected-surface: '#edf2e8'
typography:
  display:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif
    fontSize: clamp(28px, 3vw, 38px)
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: -.035em
  display-emphasis:
    fontFamily: Georgia, "Times New Roman", serif
    fontSize: clamp(28px, 3vw, 38px)
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: -.035em
  headline:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.6
    letterSpacing: -.025em
  title:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif
    fontSize: 17px
    fontWeight: 650
    lineHeight: 1.6
    letterSpacing: -.02em
  body:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif
    fontSize: 14px
    lineHeight: 1.6
  label:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif
    fontSize: 12px
    lineHeight: 1.6
  field-label:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif
    fontSize: 13px
    fontWeight: 600
    lineHeight: 1.6
  input:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif
    fontSize: 16px
    lineHeight: 1.6
rounded:
  surface: 16px
  control: 10px
  input: 9px
  icon: 8px
  secondary: 7px
  badge: 6px
  chip: 5px
spacing:
  space-4: 4px
  space-6: 6px
  space-8: 8px
  space-10: 10px
  space-12: 12px
  space-14: 14px
  space-16: 16px
  space-18: 18px
  space-20: 20px
  space-24: 24px
  space-28: 28px
  space-32: 32px
  space-48: 48px
components:
  button-primary:
    backgroundColor: '{colors.forest}'
    textColor: '{colors.paper}'
    rounded: '{rounded.control}'
    padding: 14px 18px
    width: 100%
  button-primary-hover:
    backgroundColor: '{colors.forest-hover}'
  button-secondary:
    textColor: '{colors.forest}'
    typography: '{typography.label}'
    rounded: '{rounded.secondary}'
    padding: 7px 12px
  button-secondary-hover:
    backgroundColor: '{colors.sage}'
  button-text:
    textColor: '{colors.forest}'
    typography: '{typography.label}'
    padding: 6px 0
  button-icon:
    textColor: '{colors.muted}'
    rounded: '{rounded.icon}'
    height: 36px
    width: 36px
  button-icon-hover:
    backgroundColor: '{colors.sage}'
    textColor: '{colors.forest}'
  course-input:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.input}'
    rounded: '{rounded.input}'
    padding: 14px 15px
    width: 100%
  course-chip:
    backgroundColor: '{colors.meadow}'
    textColor: '{colors.forest}'
    typography: '{typography.label}'
    rounded: '{rounded.chip}'
    padding: 2px 8px
  course-chip-invalid:
    backgroundColor: '{colors.error-surface}'
    textColor: '{colors.rust}'
  composer:
    backgroundColor: '{colors.paper}'
    rounded: '{rounded.surface}'
    padding: '{spacing.space-28}'
  activity:
    backgroundColor: '{colors.meadow}'
    rounded: '{rounded.surface}'
    padding: '{spacing.space-28}'
  quality-option:
    rounded: '{rounded.control}'
    padding: 13px
  quality-option-selected:
    backgroundColor: '{colors.selected-surface}'
  masthead:
    height: 88px
  phase:
    backgroundColor: '#dfe7d5'
    textColor: '#436047'
    typography: '{typography.label}'
    rounded: '{rounded.badge}'
    padding: 3px 9px
---

# Design System: XJTLU PaperForge

## Overview

**Creative North Star: "A quiet archive desk"**

Warm cream, paper white and muted forest green make the workbench feel calm and dependable. Chinese system typography and clearly separated controls keep the interface practical; a restrained Georgia italic gives the word Paper a small editorial accent.

The supplied-reference companion adds expression without replacing readable status. Seven colored raster expressions, a soft paper rim, an offset shadow and three small terracotta SVG mushrooms form the established illustration language. Preserve this restrained material character as the interface grows.

**Key Characteristics:**

- Warm neutral surfaces with forest-green actions.
- Readable Chinese system typography and restrained serif emphasis.
- Gently rounded surfaces, fine dividers and sparse ambient depth.
- Seven supplied-reference expressions paired with explicit status text.
- Responsive stacking and motion that respects reduced-motion preferences.

## Colors

The palette is warm and subdued. The frontmatter is the normative color source; the names below describe its roles.

### Primary

- **Forest / Forest Hover:** primary actions, the brand mark, selected control details and active progress labels. The deeper hover shade marks an available action.
- **Sage:** quiet hover fill for secondary and icon actions.
- **Selected Surface / Selected Border:** the checked quality option's pale green fill and visible green boundary.

### Secondary

- **Rust / Error Surface:** invalid course chips and incomplete result emphasis use warm terracotta text and a pale warm background. The phase-review badge has its own existing warmer treatment; it is not a second action color.

### Neutral

- **Cream:** the page ground.
- **Paper:** the composer, fields and light text on the primary action.
- **Meadow:** the activity surface and valid course chips.
- **Ink / Muted:** primary information and supporting copy, respectively.
- **Line:** structural dividers and resting option boundaries.
- **Focus Ring:** visible keyboard focus around interactive controls.

Color supports the written state. Selection also changes a radio indicator; incomplete results retain explicit status labels.

## Typography

The UI uses the system sans stack defined in the frontmatter, including Microsoft YaHei for Chinese. Georgia with Times New Roman fallback appears only in the italic Paper emphasis. No web-font download is required.

The display role belongs to the opening question; its emphasis shares the display scale and spacing. The headline role belongs to companion status, title to section headings, body to ordinary interface text, label to helper copy and counters, field-label to form labels, and input to course entry. Body text uses a comfortable inherited line height. Helper copy uses slightly more air: field help (1.7), messages and paths (1.8). The companion message is limited to (33em). Numerical progress uses tabular figures.

**The Functional Type Rule.** Functional text stays at 12px or larger, including narrow layouts.

## Layout

The current workbench sits in a centered shell with a maximum width of (1184px) and desktop horizontal padding of (48px). Its two equal columns use a (24px) gap. Main surfaces have (28px) interiors, and related form groups use a recurring (24px) separation. The header is (88px) tall; the opening section uses (45px) above and (32px) below.

At (960px) and below, shell padding becomes (28px), the column gap becomes (18px), and surface interiors become (24px). At (740px) and below, the shell has a maximum width of (580px), horizontal padding of (22px), and a single column with a (20px) gap. The header becomes (74px), the local badge hides, and the footer stacks. At (390px) and below, shell padding becomes (16px), surface interiors become (20px), and stage labels wrap into two columns. Quality choices remain side by side with adaptive padding and wrapping.

The spacing scale records recurring values from the implementation; it does not require every gap to be identical. Long paths and filenames wrap within their surface. On a narrow screen, starting work scrolls the activity surface into view, using an immediate scroll when reduced motion is requested.

## Elevation & Depth

Depth comes mainly from cream, paper and meadow layering. Only the paper composer has the ambient surface shadow. The paper props and transient toast carry small role-specific shadows; ordinary fields, badges and secondary actions remain flat. The companion's paper rim and offset shadow are part of the supplied-reference raster treatment. Exact shadow declarations live in the sidecar and source stylesheet rather than a separate frontmatter token group.

The primary button rises slightly on hover and settles on press. This feedback is restrained and is removed under reduced motion.

## Shapes

Main surfaces use the surface radius (16px); primary buttons and quality options use the control radius (10px). Course input, icon buttons, secondary actions, phase badges and course chips use their smaller role-specific radii from the frontmatter. Keep the clear distinction between a broad surface and a compact control.

The brand mark retains its asymmetric leaf-like corner treatment (10px 10px 14px 10px). Fine borders divide content without boxing every line. A low elliptical ground, small paper rectangles and three mushroom silhouettes provide the scene's supporting geometry. The supplied raster silhouettes retain clean colored edges and a soft paper rim.

## Components

### Buttons

Primary actions are solid forest with paper text, semibold type and a full-width layout. Hover uses the deeper forest shade, moves the button up (2px), and moves the arrow right (3px). Pressing a button moves it down (1px). Disabled buttons use opacity (.52), a default cursor and no transform.

Secondary actions use a fine green outline, compact label type and a sage hover fill. Text actions remain transparent and underline on hover. Icon actions have quiet square hit areas; the output reset control uses the existing smaller (28px) variant. Preserve accessible names for icon-only controls. Global keyboard focus is a visible (3px) outline with (4px) offset.

### Inputs / Fields

Course entry uses a paper fill, muted thin border and the input typography role. Focus shifts to a forest border with a lighter (2px) outline and white fill. Invalid entry changes the border to rust and presents a written error. Helper copy sits below the field. Quality options are semantic radio labels: selection changes the background, boundary and radio dot; keyboard focus outlines the entire option. Disabled options use opacity (.6). Forced-colors mode exposes the native radio inputs.

### Chips / Status

Course chips are compact, softly squared meadow labels with forest text. Invalid chips use the error pair. Phase labels use quiet green fills in normal states and a warm review treatment when attention is needed. Keep phase and result words visible; the colored treatment is supplementary.

### Cards / Containers

The composer is warm paper with ambient depth. The activity surface is flat meadow. Both share the same surface radius and responsive interior spacing. Grouping relies on whitespace and fine dividers. Results are separated rows with course names, written status, messages and expandable file lists rather than individual elevated cards.

### Navigation

The header pairs the leaf mark and wordmark with a local-workbench indicator and exit action. The wordmark links home. It remains compact on mobile, and the local indicator hides to preserve room. The sidecar preserves the actual header primitive rather than inventing a navigation menu.

### Companion / Progress

Use exactly seven local supplied-reference expressions: idle, starting, searching, downloading, validating, success and issue. Waiting reuses idle; cancelling and cancelled reuse validating. The scene contains three authorized small SVG mushrooms and two paper props. Keep the scene decorative and the adjacent status text authoritative.

Manual school authentication displays “请去登录哦” with a readable 14px forest-colored instruction naming the task's actual browser. This is driven by the worker's waiting event, not by every connection attempt. The start button and account label also say that login is awaited; the prompt clears when processing resumes or is cancelled.

Only searching, downloading and validating loop the gentle thoughtful motion (2.4s). Starting has a single departure motion (650ms); complete has a single celebration (850ms) and mushroom sway (900ms). Waiting and error states do not loop. Hidden-page and offscreen activity animation is paused. Under reduced motion, animations and transitions are disabled, hover translation is removed, and scrolling is immediate.

The progress track is compact (7px). Its numerator counts fully archived courses; verified PDF counts remain separate, and unknown totals stay unknown. A success expression belongs only to a fully complete run. Partial results use the issue expression and explicit review status.

## Do's and Don'ts

### Do:

- Do preserve the cream, paper and meadow surface hierarchy with forest-green actions.
- Do keep functional text at 12px or larger and preserve visible keyboard focus.
- Do use the seven colored supplied-reference expressions and the authorized small SVG mushrooms.
- Do make waiting, partial, failed and cancelled states readable in text as well as color.
- Do pause offscreen or hidden animation and remove animation and transitions under reduced motion.

### Don't:

- Don't replace the supplied companion with an unrelated character or add an eighth expression.
- Don't treat unknown workload as a percentage or use the success expression for partial results.
- Don't introduce remote fonts or dynamic external imagery into this local visual system.
- Don't make buttons, fields or status text compete with large decorative effects.
