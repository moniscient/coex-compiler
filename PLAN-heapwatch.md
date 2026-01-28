# Heapwatch v1 Implementation Plan

## Overview
A visual heap monitoring library that renders an ImGui panel showing heap statistics and TLAB utilization. Called from the main game loop via `heapwatch.render()`.

## Design Principles
- **No GC modifications** - only read existing stats via minimal getter functions
- **Pure Coex library** - `lib/heapwatch.coex`
- **ImGui panel** - renders within existing window, not separate OS window
- **Simple API** - just `import heapwatch` and call `heapwatch.render()`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Main Window                                                │
│  ┌─────────────────────────────────┬──────────────────────┐ │
│  │                                 │  HEAPWATCH           │ │
│  │     User's Game/App             │  ┌──┬──┬──┬──┐       │ │
│  │                                 │  │██│▓▓│░░│  │ ...   │ │
│  │                                 │  ├──┼──┼──┼──┤       │ │
│  │                                 │  │▓▓│░░│  │  │       │ │
│  │                                 │  └──┴──┴──┴──┘       │ │
│  │                                 │  Handles: 28K/1M     │ │
│  │                                 │  TLABs: 18 reclaimed │ │
│  └─────────────────────────────────┴──────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Required GC Getter Functions

Add minimal extern functions that return existing GC stats (read-only):

```coex
# These read from existing gc_stats struct and debug counters
extern gc_get_total_allocations() -> int ~
extern gc_get_total_bytes() -> int ~
extern gc_get_collections() -> int ~
extern gc_get_live_objects() -> int ~
extern gc_get_swept_objects() -> int ~
extern gc_get_next_handle() -> int ~
extern gc_get_handle_table_size() -> int ~
extern gc_get_tlabs_reclaimed() -> int ~
```

These are trivial one-line functions that just load and return a global value.

## Heapwatch Library (lib/heapwatch.coex)

```coex
import ui

# GC stat getters (extern to C)
extern gc_get_total_allocations() -> int ~
extern gc_get_total_bytes() -> int ~
extern gc_get_collections() -> int ~
extern gc_get_live_objects() -> int ~
extern gc_get_swept_objects() -> int ~
extern gc_get_next_handle() -> int ~
extern gc_get_handle_table_size() -> int ~
extern gc_get_tlabs_reclaimed() -> int ~

# Render the heapwatch panel
# Call this from your main loop after ui.render()
func render() -> int
    # Get current stats
    total_allocs = gc_get_total_allocations()
    total_bytes = gc_get_total_bytes()
    collections = gc_get_collections()
    live = gc_get_live_objects()
    swept = gc_get_swept_objects()
    next_handle = gc_get_next_handle()
    table_size = gc_get_handle_table_size()
    tlabs_reclaimed = gc_get_tlabs_reclaimed()

    # Calculate derived metrics
    handle_usage_pct = (next_handle * 100) / table_size
    avg_allocs_per_gc = total_allocs / (collections + 1)

    # Build panel layout
    panel: json = {
        type: "window",
        title: "Heapwatch",
        children: [
            # Stats section
            { type: "text", text: "=== Heap Statistics ===" },
            { type: "text", text: "Allocations: " + String.from(total_allocs) },
            { type: "text", text: "Total Bytes: " + format_bytes(total_bytes) },
            { type: "text", text: "Collections: " + String.from(collections) },
            { type: "text", text: "Live Objects: " + String.from(live) },
            { type: "separator" },

            # Handle table section
            { type: "text", text: "=== Handle Table ===" },
            { type: "text", text: "Next Handle: " + String.from(next_handle) },
            { type: "text", text: "Table Size: " + String.from(table_size) },
            { type: "progress", fraction: handle_usage_pct / 100.0 },
            { type: "text", text: String.from(handle_usage_pct) + "% used" },
            { type: "separator" },

            # TLAB section
            { type: "text", text: "=== TLABs ===" },
            { type: "text", text: "Reclaimed: " + String.from(tlabs_reclaimed) },
            { type: "text", text: "Memory freed: " + format_bytes(tlabs_reclaimed * 262144) }
        ]
    }

    # Render panel (uses same state as main UI)
    ui.render(panel, "{}")
    return 1
~

# Format bytes as human-readable string
func format_bytes(bytes: int) -> string
    if bytes < 1024
        return String.from(bytes) + " B"
    ~
    if bytes < 1048576
        return String.from(bytes / 1024) + " KB"
    ~
    if bytes < 1073741824
        return String.from(bytes / 1048576) + " MB"
    ~
    return String.from(bytes / 1073741824) + " GB"
~
```

## Usage in Galaxian

```coex
import ui
import svg
import heapwatch  # Add this import

func main() -> int
    # ... initialization ...

    while game_over == 0
        # ... game logic ...

        # Render game
        state = ui.render(layout, state)

        # Render heapwatch panel (shows alongside game)
        heapwatch.render()
    ~

    # ... cleanup ...
~
```

## Visual Grid (Future Enhancement)

For v1, use text + progress bars. Future versions could add a visual grid:

```coex
# Generate SVG grid showing TLAB states
func render_tlab_grid(width: int, height: int) -> json
    # Would need per-TLAB state info from GC
    # For now, show aggregate stats only
~
```

## Implementation Steps

### Step 1: Add GC Getter Functions (coex_gc.py)
- [ ] `gc_get_total_allocations()` - load gc_stats[0]
- [ ] `gc_get_total_bytes()` - load gc_stats[1]
- [ ] `gc_get_collections()` - load gc_stats[4]
- [ ] `gc_get_live_objects()` - load gc_stats[5]
- [ ] `gc_get_swept_objects()` - load gc_stats[6]
- [ ] `gc_get_next_handle()` - load gc_next_handle
- [ ] `gc_get_handle_table_size()` - load gc_handle_table_size
- [ ] `gc_get_tlabs_reclaimed()` - load gc_debug_tlabs_reclaimed

### Step 2: Create lib/heapwatch.coex
- [ ] Extern declarations for getters
- [ ] `render()` function with ImGui panel
- [ ] `format_bytes()` helper

### Step 3: Test with Galaxian
- [ ] Add `import heapwatch` to galaxian.coex
- [ ] Add `heapwatch.render()` call in game loop
- [ ] Verify panel appears and updates

## Files to Create/Modify

### New Files
- `lib/heapwatch.coex` - The heapwatch library

### Modified Files
- `coex_gc.py` - Add 8 simple getter functions (read-only)
- `examples/galaxian.coex` - Add heapwatch import and render call (for testing)

## Success Criteria
- Heapwatch panel appears in Galaxian window
- Stats update in real-time as game runs
- No performance impact (getters are just global loads)
- Handle usage stays stable (validates BUG-062 fix)
