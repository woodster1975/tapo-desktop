---
name: Tapo Desk
description: A photographic light table for local camera footage.
colors:
  ink: "#192c27"
  background: "#f4f5f2"
  muted: "#50645c"
  error: "#a13e34"
  rail: "#e9ece6"
  stage: "#121b18"
  stage-ink: "#f3f6f1"
  stage-hint: "#b8cbc1"
  control-border: "#c5d0c7"
  paper: "#ffffff"
  control-hover: "#e2eae1"
  control-hover-border: "#91aa9d"
  control-pressed: "#ceded3"
  accent: "#175e4b"
  disabled-ink: "#718078"
  disabled-background: "#e8ece6"
  divider: "#d6ded6"
  accent-hover: "#104b3b"
  primary-disabled-background: "#d5dfd8"
  primary-disabled-ink: "#64786c"
  accent-tint: "#dae9e0"
  tab-selected-border: "#bfd4c5"
  camera-selected: "#d5e3d7"
  camera-selected-border: "#aec7b7"
  camera-hover: "#dde5dc"
  table-header: "#edf1eb"
  progress-track: "#dbe3d9"
  scroll-handle: "#a9bbac"
  timeline-track: "#dce4da"
  timeline-interval: "#80a28d"
typography:
  headline:
    fontFamily: "Lato"
    fontSize: "26px"
    fontWeight: 700
  brand:
    fontFamily: "Lato"
    fontSize: "22px"
    fontWeight: 700
  stage-title:
    fontFamily: "Lato"
    fontSize: "24px"
    fontWeight: 700
  title:
    fontFamily: "Lato"
    fontSize: "18px"
    fontWeight: 700
  body:
    fontFamily: "Lato"
    fontSize: "14px"
    fontWeight: 400
  label:
    fontFamily: "Lato"
    fontSize: "14px"
    fontWeight: 700
  support:
    fontFamily: "Lato"
    fontSize: "13px"
    fontWeight: 400
  table-heading:
    fontFamily: "Lato"
    fontSize: "12px"
    fontWeight: 700
  tile-status:
    fontFamily: "Lato"
    fontSize: "12px"
    fontWeight: 400
rounded:
  control: "8px"
  stage: "12px"
  progress: "3px"
  timeline: "4px"
  interval: "2px"
  slider-handle: "6px"
spacing:
  step-4: "4px"
  step-8: "8px"
  step-10: "10px"
  step-12: "12px"
  step-16: "16px"
  step-18: "18px"
  step-20: "20px"
  step-24: "24px"
  step-28: "28px"
  step-36: "36px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "9px 16px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "9px 16px"
  tab-selected:
    backgroundColor: "{colors.accent-tint}"
    textColor: "{colors.accent}"
    rounded: "{rounded.control}"
    padding: "9px 16px"
  field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
  camera-item-selected:
    backgroundColor: "{colors.camera-selected}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "13px 14px"
  video-stage:
    backgroundColor: "{colors.stage}"
    textColor: "{colors.stage-ink}"
    rounded: "{rounded.stage}"
  recordings-table:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
  camera-tile:
    backgroundColor: "{colors.stage}"
    textColor: "{colors.stage-ink}"
    rounded: "{rounded.control}"
    padding: "10px"
---
# Design System: Tapo Desk

## Overview

**Creative North Star: "Photographic light table"**

A calm warm-white tool surface frames a graphite video stage. Footage leads; time, camera identity and explicit actions remain visible. The native desktop interface works as a photographic light table with restrained green selection and stable alignment.

Lato supplies a consistent voice across the application. Flat surfaces, softly curved controls and textual state descriptions keep the interface practical and quiet. No decorative motion is defined.

**Key Characteristics:**
- Footage-first graphite stage within a pale workspace.
- Restrained green actions, selection and progress.
- Aligned time columns with explicit seconds.
- Native keyboard-accessible controls and text states.

Direction: photographic light table. Concept seed 8ac8811c assigned grounded candidate 4; the seven-candidate pool and verdicts are recorded below. The user explicitly delegated all design decisions and asked us to proceed, overriding interview/approval-board steps. No quality-bar comp was approved; source-native UI is the evidence for this code-first build. A calm warm-white tool surface frames a graphite video stage. Footage leads; time, camera identity and explicit actions remain visible. Native desktop, operate mode. Stack and visual decisions delegated by the user; this build proceeds code-first without an approval board.

Grounded candidates: archive room; broadcast console; film catalog; photographic light table (chosen); station departure board; library finding aid; gallery contact sheet. The light table keeps the strongest video focus and plain native controls. Challengers: spectral rail declined for obscure states, retained disciplined alignment; airport wayfinding declined as too loud for home viewing, retained unambiguous location labels; boarding-pass ledger declined for misplaced travel metaphor, retained stable ordered time columns.

This merges the newly authored provisional design into the shipped system under the user's delegated design authority. Source-native UI is the evidence; there was no approved quality-bar comp. Frontmatter is normative for extracted token values; native Qt remains the implementation source.

## Colors

A forest-green accent sits among warm pale neutrals and green-black ink. Exact shipped colors and state variants live in frontmatter.

### Primary

- **Forest green** (`accent`): primary actions, focus, text selection, active timeline interval and progress.
- **Deep forest** (`accent-hover`): primary hover.
- **Soft sage** (`accent-tint`): selected tabs and recording rows.

### Neutral

- **Warm workspace**, **paper** and **sage rail**: window, table/fields and navigation respectively.
- **Green-black ink** and **quiet ink**: primary and supporting text.
- **Graphite stage**, **stage white** and **stage sage**: footage enclosure and instructional empty-state copy.
- Dedicated control, camera-row, header, divider, scrollbar, timeline and disabled tokens preserve the native state vocabulary.

The error token is reserved for textual failure feedback.

**The State Has Words Rule.** Color reinforces selection and status; visible text identifies connection, playback, failure and work states.

## Typography

**Application Font:** bundled Lato regular and bold, using native Qt Fusion widget metrics. No distinct display or monospace family is implemented.

### Hierarchy

- **Headline:** current camera identity.
- **Brand:** application name.
- **Stage title:** instructional empty-state heading.
- **Title:** rail and recording section headings.
- **Body / label:** regular widget copy and bold actions.
- **Support:** metadata, captions and hints.
- **Table heading:** compact bold ledger headings.
- **Tile status:** compact regular-weight live-state labels within the camera wall.

Sizes and weights are recorded in frontmatter. The custom timeline requests Lato at 10 Qt points, not a stylesheet pixel size. Line height follows font metrics; no letter-spacing token exists. Recording times are center-aligned in stable columns, with seconds and full local ISO timestamps including UTC offsets in tooltips. No explicit tabular-number font feature is enabled.

## Layout

The window opens at 1440 × 900 with a minimum of 1060 × 700. The fixed camera rail (224px) anchors an expanding workspace. Workspace margins are (28px horizontal, 24px top, 16px bottom), with section spacing (18px). Rail margins are (20px horizontal, 28px top, 20px bottom).

The first screen places Live view, Recordings and Camera wall mode navigation above the content. Recordings uses a resizable horizontal split: expanding viewer and a ledger with requested initial width (340px). The table minimum is (300px); split-side inner gutters are (12px). Three columns—Preview, Start / length and Detection—have steady rows (64px). Preview has a fixed width (96px) and aspect-preserving images (80 × 45px); the other two columns stretch. Start and length share two centered lines. The selected preview below the ledger retains its larger enclosure (120 × 68px). The stage has a minimum height (220px), keeps media aspect ratio and uses spacious empty-state padding (36px).

This rail/viewer/ledger arrangement is the first-surface expression, not a mandatory composition for future dialogs. Live mode hides recording-specific controls. Desktop resizing uses native layouts and splitters; no mobile breakpoint or web reflow exists. The seed's 32px spacing step did not become a reused shipped token; frontmatter records actual shared values. Status text may wrap, and progress remains visible while a job is active.

Camera wall replaces the single viewer with a graphite scrollable canvas. Its native grid uses equal stretch, outer padding and gutters (12px), with tile padding (10px) and internal spacing (8px). One camera prefers one column; two to four cameras prefer two; larger sets prefer three. Available viewport width reduces the count using a (250px) column budget. Canvas minimum height budgets (180px) per row plus gutters and outer padding, allowing vertical scrolling. Focus expands the chosen tile into one row and column while the other players continue independently. This is native desktop reflow, not a web breakpoint.

## Elevation & Depth

No decorative shadows or gradients are defined. Depth comes from the dark footage stage, pale rail, white fields and table, tonal selection and thin borders. Native dialogs retain platform window treatment. No custom animation duration or easing tokens are implemented.

**The Footage Leads Rule.** Keep the highest visual contrast around the video stage; surrounding controls support viewing and retrieval.

## Shapes

Gently curved controls, camera rows and the ledger share the control radius; the stage uses the larger stage radius. Thin one-pixel borders define fields, buttons and selected camera rows. Progress, timeline and slider geometry use the smaller radii in frontmatter. No decorative card or pill-chip component is implemented.

## Components

### Buttons

Plain, confident actions. Primary uses forest green and white; secondary uses paper and ink. Shared bold lettering, radius and padding are tokenized. Secondary hover changes fill and border; pressed state darkens the pale fill. Primary hover deepens green. Focus increases the border to two pixels and reduces padding by one pixel to avoid size jumps. Disabled primary and secondary controls use separate muted palettes. Primary focus inherits the same green border as its fill; a separate contrasting focus halo is not implemented.

### Inputs / Fields

White line edits, combo boxes and date fields share rounded borders and compact padding. Focus strengthens the accent border with compensating padding; disabled line edits and combo boxes use muted colors. Native dropdown regions are (24px). Password fields use native concealed text.

### Navigation

Camera rows pair name and address. Sage fill and border indicate selection; hover uses a pale sage. Camera-list focus adds an accent perimeter. Mode buttons are transparent and muted at rest, with green-tinted fill, green text and subtle borders when checked. Live view, Recordings and Camera wall are exclusive native checkable buttons. In the wall, selecting a camera in the rail focuses its tile and keeps camera identity synchronized.

### Video Stage

The signature graphite enclosure switches between centered instructional text and an aspect-preserving Qt video widget. Caption, transport and playback time remain below. Playback and download are explicit actions; preparation and ongoing work appear in shared status/progress. The 190px native Audio output combo sits in the top toolbar for single live view and recordings and is hidden in the wall. System default is initial, other available device names can be chosen and are remembered. If the playback clock stalls, the player detaches audio and attempts to continue video muted, with an explicit recovery message, an Unmute action and guidance to choose another output. The compact primary transport label is Play clip to leave room for Unmute.

### Camera Wall / Live Tile

The photographic light table extends to simultaneous footage. Tiles reuse the graphite stage background and control radius. A thin muted-ink border separates each tile; keyboard focus strengthens it to a two-pixel stage-hint border. Bold stage-white camera name and address remain above the image alongside a compact regular-weight stage-hint status. Video keeps its aspect ratio; an instructional or failure message occupies the same area before frames arrive. Text identifies Stopped, Queued, Connecting, Live and Unavailable states; an applicable failure exposes a Reconnect button using the existing secondary style.

Double-click a tile, or press Enter while it has keyboard focus, to toggle focused viewing. Double-click again, press Escape while focused, or choose Back to all cameras to restore the grid. Focus rearranges existing players without reconnecting streams. All tiles start muted; only the focused tile can be explicitly unmuted, and focus changes mute all audio. Stop disconnects every wall stream. One unavailable camera leaves other tiles independent. The shared heading reports All cameras or the focused identity, and the summary reports live count and pending connection text.

The wall toolbar uses the existing native combo-box treatment for **Wall: smooth video** (default lower-bandwidth stream2) and **Wall: full detail** (stream1). This setting is specific to the wall; single-camera Live view retains its Edit camera quality. Changing wall quality reconnects the wall, while focus/back preserves the current streams and quality. Queued tiles show Waiting to connect before staggered starts; audio remains detached until explicitly unmuted on the focused tile.

### Recordings Ledger

A white rounded table with pale headers, no visible cell grid and centered Preview, Start / length and Detection columns. Detection reports camera event counts or an explicit recording state; the native filter offers All recordings and With detections. The whole row is selected. Selection updates the stage caption and the corresponding interval in the day overview, with local event timestamps and numeric camera type codes in the details below the ledger.

Visible rows request previews automatically after a viewport throttle (120ms), using one serialized background worker and a private JPEG cache. Scrolling replaces queued offscreen work and cancels a slow obsolete request when new visible rows need images. One following page is prefetched after visible requests. Text identifies pending, continuous and unavailable previews; missing results remain cached until refresh, context change or explicit Retry preview. The selected larger preview shares these results. Background preview work leaves the controls enabled; foreground camera operations and live view take priority and pause preview work; local recording playback allows previews to continue. Context changes and window close cancel stale work. Play clip streams the selected recording on the existing stage without waiting for a complete file; double-clicking a row does the same. Streaming disables seeking, supports pause/Stop and pauses camera thumbnail work. Download saves a copy to the chosen destination.

### Day Timeline and Progress

A read-only custom-painted day overview displays muted intervals on a pale track. The selected interval becomes darker and taller. Labels mark 00:00, 06:00, 12:00, 18:00 and 24:00. Selection happens through the ledger; timeline pointer-selection is not implemented. The playback seek slider is separate. Job progress uses a slim accent bar with indeterminate mode when total work is unknown.

## Do's and Don'ts

### Do:
- Do preserve footage aspect ratio and keep camera identity visible.
- Do use green consistently for actions, selection, focus and progress.
- Do retain explicit seconds and offset-bearing exact-time tooltips.
- Do accompany connection, failure and work states with text.
- Do keep keyboard focus visible and disable unavailable actions.

### Don't:
- Don't add decorative shadows, gradients or ornamental motion to the flat workspace.
- Don't substitute color alone for an action or status label.
- Don't expose credentials in visible URLs, labels or tooltips.
- Don't introduce an unrelated display family or replace footage with decorative dashboard cards.

<!-- 0.4.2 tile presentation: Wall tiles use ordinary QWidget/QPainter image presentation through QVideoSink, rather than native video windows. Preserve the existing stage palette, aspect ratio, identity and focus/back controls. Frame presentation is bounded to 10fps; single-view media stays separate. -->

Dropdown popup readability

Combo-box popup lists use the existing paper (#ffffff), ink (#192c27), control border (#c5d0c7) and selected tint (#dae9e0), with ink retained on selected rows. Items have a minimum height (28px) with vertical (4px) and horizontal (10px) padding. Disabled entries use the existing disabled colors. Popups use the styled scrollable list rather than a system menu that can mix dark surfaces with light-theme text rules. The recording date picker limits the visible list to ten entries; all dates remain reachable by scrolling. No new tokens or visual world.
