# GUI Agent Instructions

These instructions apply to work on the Critical-Grid GUI.

## Project design overview

- Critical Grid is a top-down, 2D, pausable real-time tower defense and resource-management game. The player commands a frontier base, plans construction during the day, and responds to enemy attacks at night. The core is the objective to protect.
- The central decisions are how to spend gold, build a connected power grid, and balance economic growth against immediate defense. Power shortages reduce building effectiveness. Emergency options such as core overdraft and tower overload provide short-term help at a future cost through debt or repair pressure.
- The V0.2 design target includes eight night waves, construction and repair, power-grid disruption, time controls, and clear victory or defeat. The demo runs for eight nights and implements part of that ruleset; treat the code as the behavior source of truth and the design document as the target.
- The interface should use a central map, a persistent resource and status HUD, and a selection/details panel. Show gold, power supply and demand, efficiency, debt, core health, phase, wave, speed, and pause state where supported by the current snapshot. Make placement validity, power loss, damaged buildings, enemy threats, and failed actions understandable. Use text or symbols in addition to color for important states.
- The intended visual style is minimal and legible, like an engineering control console. Keep the map visible while menus and details are open. Prefer clear feedback and explainable failures over decorative effects.
- All player-facing text in the game must be in English, including menus, buttons, HUD labels, prompts, status messages, and errors shown by the GUI.
- Team ownership: the collaborator develops core game rules in `grid_td`; this developer develops interaction and presentation in `gui`, using Python, Pygame, and pygame_gui. `GameState` owns authoritative gameplay state. The GUI displays snapshots and sends commands through public methods.
- Before implementing a design feature, compare the V0.2 design document (`GAME_DESIGN(3).md`, 2026-10-11) with the current code and snapshot contract. The document is external to this repository. If it is unavailable, use this overview and report any missing design detail or core API needed for the task.

## Current core rules (verified against grid_td at 5a5fdb3 on 2026-11-08)

- `GameState` owns gold, debt, core HP, buildings, enemies, waves, and the authoritative logical clock. A new game starts in `GamePhase.DAY`; `step(seconds)` does not advance time during DAY. The player calls `start_next_wave()` to enter NIGHT. Pause is a frontend choice to withhold steps, not a core phase.
- During NIGHT, the core spawns enemies, resolves tower attacks, moves enemies along their planned routes, and handles breach and building attacks. After all enemies spawn and the board is clear, end_wave() grants the night’s base reward, settles the wave, and returns to DAY or records VICTORY. Core destruction records DEFEAT.
- The demo map is 36 by 21 small cells. Each former map tile was subdivided into 3 by 3 cells; one small cell spans one world unit. `Position` names an integer cell, while `WorldPosition` names a continuous point. Current buildings, including the core, occupy 3 by 3 cells; `Building.position` is the top-left anchor. Custom footprints are supported by the core.
- Roads are terrain and can be built on outside reserved entrances and other prohibited cells. Enemies find their own routes around buildings and can breach blockers. The immutable level definition supplies the map, waves and starting resources. Each spawn group selects a declared entrance. The bundled demo has two entrances.
- `preview_build(kind, anchor)` checks the same whole-footprint terrain, occupancy, mine-site, gold, and terminal-state rules as `build()` without mutation. Ordinary placement failures return `BuildPreview.is_valid=False` and a reason; malformed inputs raise `ValueError`. Only mines fit on mine terrain, and a tower gets its high-ground range bonus only when its full footprint is on high ground. `build()` rechecks before charging gold.
- Power reaches buildings within the grid radius of a connected transmitter. The core, power plants and live nodes can relay power. Damaged nodes retain their radius and reduce the transmission quality of downstream consumers. The grid allocates supply by priority tier, then shares any shortage proportionally within the tier. Final output combines allocated power, health and transmission.
- Every building has mutable HP. `repair_building(id)` instantly restores full HP for one gold per missing HP during DAY or NIGHT, including zero-HP non-core buildings that remain on the map. A destroyed core cannot be repaired. Successful repair refreshes the power grid. `BuildingSnapshot` exposes `hp`, `max_hp`, and `repair_cost`; HP repair does not clear overload service markers or debt.
- Snapshots report allocated power, health efficiency, transmission efficiency, final output, direct source IDs and effective generator supply. The HUD total counts connected supply. A disconnected generator contributes zero to the grid.
- `sell_building(id)` removes any non-core building and refunds `round(cost * 0.7)` gold, then refreshes the grid; the core cannot be sold and ended games are rejected. `set_tower_target(tower_id, enemy_id)` and `clear_tower_target(tower_id)` control a tower's manual target, which is honored only while the target stays alive and in range. Every active enemy now has a stable runtime `id` exposed as `EnemySnapshot.id`, and towers expose `BuildingSnapshot.target_enemy_id` (default `None`). The older `demolish_tower(id)` still removes a tower with no refund and no terminal-phase guard.
- The core supplies 10 power and starts at 30 HP; the bundled demo starts with 220 gold. Kills pay immediately. Mines pay at wave settlement according to efficiency; settlement also charges 12% interest on total debt and 5 gold per overload service marker without restoring HP. `core_overdraft()` defaults to +40 gold and +54 debt; `overload_tower()` defaults to 8 logical seconds, adds 10 debt, boosts damage and attack speed, and marks the tower for that settlement fee.
- The demo includes mines, power plants, power nodes, three tower types and four enemy types. Cannon splash and flat armor affect combat. Saboteurs seek power infrastructure and may switch to another in-range target. Other enemies can attack selected buildings or breach path blockers.

## Design gaps in the current core

- **Routing and map variety:** Dynamic per-enemy routes and multiple entrances are available. Construction previews show placement and ranges. A prediction of how a proposed placement would reroute enemies still needs a read-only core API. The bundled demo contains eight waves.
- **Building lifecycle:** Build timers, upgrades and partial repairs are still absent. HP repair and overload service fees are separate systems.
- **Combat behaviors:** Snapshots expose splash size and damage, enemy building attacks, and manual targets. An actual hit animation still needs authoritative attack events.
- **Power and economy:** The core tracks direct power sources and per-consumer priority. Each settled night grants a configured base reward. Debt repayment and debt-source breakdown remain unavailable.
- **Wave intelligence:** GameStatus exposes free_intel, detailed_intel and intel_price. The core charges once per wave, and the GUI reads both tiers during DAY and NIGHT. WaveIntel does not expose the base reward. Keep exact counts, timing and route geometry in the purchased tier.
- **Time and campaign rules:** The core accepts logical step durations but has no stored speed multiplier or bullet-time state. The frontend owns its pause, speed, and bullet-time policy, described below. Scoring and additional victory/failure conditions beyond final-wave survival and core destruction are absent.
- **Presentation data:** BuildPreview provides potential reach. GameSnapshot exposes entrances, enemy routes, attack targets and structured wave intel, and building snapshots expose direct sources. Draw these relationships from snapshots. Do not infer combat events or connections.

## Current GUI coverage

- Wave Overview is always visible below the map and shows the current wave, threat, enemy types, traits, entrances and briefing.
- The purchase button uses the current snapshot price. Detailed Intel has scrollable Groups and Timeline pages for purchased counts, spawn times and the estimated duration. The next wave resets the panel to the locked state and uses the new snapshot. Enemy entrances use the board order for E1 and E2.
- The level card and gameplay use the same validated demo TOML definition. Numbered entrance markers match enemy inspection labels. Select an enemy to show its assigned route and outline its attack or breach targets.
- Select a building to see the direct power links touching it. Green links have full transmission and amber links have reduced transmission. The sidebar displays the selected building’s direct source, individual efficiency factors and actual versus rated supply where applicable.
- The power-priority control has a separate row above the details panel and shows the current tier for the selected consumer.
- Before placement, hovering a power node or plant shows potential transmission reach in green; hovering any attack tower shows attack range in blue. Invalid placements retain their range in red and display the rejection reason. Ranges stay within the map beneath units, with the candidate footprint drawn on top. Coverage describes potential reach and does not promise grid connectivity or attack availability.
- `BuildPreview.center`, `attack_range`, and `power_radius` provide authoritative candidate geometry, including full-footprint high-ground bonuses and the configured grid radius. The GUI uses these read-only fields and the shared `world_distance()` policy instead of duplicating gameplay rules. Optional defaults preserve footprint-only previews. Previewing must not spend gold, allocate building IDs, or change power state.
- Run hover-range regressions with `python -m unittest gui.test_range_preview` alongside `gui.test_interactions` and the core suite. Cases include actual cursor hover, all attack towers, configured grid radii, full versus partial high ground, rectangular centers, invalid placement, and clipping.
- The 1080-by-840 GUI keeps the 36-by-21 map at its existing 18-pixel cell size and 54-by-54-pixel building footprints. It draws continuous enemy positions from snapshots, uses `preview_build()` for hover feedback, and returns to DAY after each settled night. Controls include Start Night, Run/Pause, Step +1s, construction, Sell Building, Repair HP, overload, wave intel, and core overdraft. Building rings and `LOW`/`OFF` labels retain connectivity/output feedback without implying power-source links. Damaged buildings have separate HP bars.
- Every building, including the core, can be selected through `selected_building_id`. Sell Building shows the estimated refund using the core's public `SELL_REFUND_RATIO`; successful sale messages use the command's returned refund. Repair HP shows `repair_cost`, applies to HP damage only, and remains separate from `needs_repair`, which marks an overload service fee at settlement. Rejections display the core's `ValueError`. Details distinguish allocated power, condition, transmission, final efficiency, supply and demand.
- Clicking an enemy marker selects its stable ID and shows HP, armor, base speed before slow effects, slow state, reward, core damage, route progress, and world position. Selection follows movement and clears when the enemy leaves the snapshot. Armor badges show `ARM 2` for armored enemies, and slowed enemies have a separate outline. Picking and drawing share marker coordinates, including offsets for crowded cells.
- Select a tower, press Set Target or `T`, then click an enemy. Target mode keeps the tower selected until a valid command succeeds or the player cancels. A gold `TARGET #id` ring and the details panel show the manual target from the snapshot. Clear Target resumes automatic targeting. The core owns target validity and automatic fallback after death or leaving range; the GUI never infers an automatic target. `O` overloads towers, `R` repairs selected buildings, Delete sells, and Escape cancels construction or targeting.
- Speed buttons and keys `1`, `2`, and `3` select 0.5x, 1x, and 2x. During a running NIGHT, construction mode or inspection of an HP-damaged building caps the effective speed at 0.25x. The preferred speed resumes after placement/cancellation, repair, or selection of undamaged/empty terrain. The HUD shows both preferred speed and active bullet time. Scale accumulated real time, then call `step(0.05)` in fixed increments. DAY and pause never accumulate catch-up time. Step +1s pauses first and advances up to one logical second regardless of speed or bullet time, stopping immediately at settlement or a terminal phase.
- Run GUI regressions with `python -m unittest gui.test_interactions` and the existing core suite with `python -m unittest discover -s tests`. GUI tests use SDL dummy video/audio drivers and cover public command routing, selection, repairs, refunds, target fallback, logical time, and rendering. Keep new GUI tests under `gui/` to respect ownership.
- The external V0.2 design document is not included in this checkout. The GUI follows the current snapshot contract.

## Sprite art and previews

- Keep building sprites legible at the current 3-by-3-cell, 54-by-54-pixel footprint. New building candidates use a 48-by-48-pixel transparent canvas and leave a small margin inside the footprint. The GUI currently selects `core-v2.png`, `mine-v1.png`, and `gun-tower-v2.png` by snapshot building kind.
- Use a consistent top-down, slightly raised view, dark outlines, restrained engineering-console colors, and a clear silhouette for each building role. Prefer readable machinery over tiny decorative detail.
- Save editable LibreSprite sources beside their transparent PNG exports under `gui/assets/buildings/`. Keep review previews under `gui/assets/previews/`; scale pixel art for review with nearest-neighbor sampling.
- Do not bake terrain grid lines, status rings, selection borders, HP bars, labels, or other snapshot-dependent UI into a sprite. Render those states separately in the GUI. Imported sprites omit the normal green power ring, while `LOW` and `OFF` warnings remain visible.
- Show sprites in previews against a uniform dark ground color without gray map grid lines. Imported sprites also need a terrain-colored backing in the game so the map grid does not show through transparent pixels.

## Change scope

- Create, edit, move, or delete files only under `gui/` relative to the repository root.
- Reading files elsewhere in the repository is allowed for understanding interfaces and behavior.
- Do not modify `grid_td`, `tests`, `main.py`, `README.md`, or other files outside `gui`. If a task requires such a change, report the dependency and proposed change to the user instead of making it.

## Code comments

- Add concise English docstrings or comments to new or substantially changed core GUI functions.
- Explain purpose, important behavior, and non-obvious decisions. Keep comments accurate and avoid narrating obvious statements.

## Game state interface

- Use `GameState.snapshot()` as the source of data displayed by the GUI. Read status, cells, buildings, and enemies from the returned snapshot rather than from mutable game entities or private fields.
- `GameSnapshot` exposes map dimensions, `cell_size`, `distance_metric`, status, and a row-major board. `GameStatus.phase` distinguishes DAY/NIGHT/VICTORY/DEFEAT. A building appears in every cell of its footprint; deduplicate by `BuildingSnapshot.id`, and use its `position`, `width`, `height`, and `center`. Use `EnemySnapshot.world_position` for drawing; `position` is only its containing cell.
- Treat `CellSnapshot.is_buildable` as a single-cell hint, not whole-building approval. Use `preview_build()` for the complete footprint and rejection reason, then let `build()` validate again. Do not turn physical `path_progress` into a route waypoint index.
- Render candidate ranges from `BuildPreview.center`, `attack_range`, and `power_radius`. A missing radius means that range does not apply; `power_radius` is potential reach only. Keep high-ground checks and grid configuration inside the core preview command.
- Perform gameplay actions through public `GameState` commands: `start_next_wave()`, `step()`, `end_wave()`, `preview_build()`, `build()`, `repair_building()`, `sell_building()`, `set_tower_target()`, `clear_tower_target()`, `buy_wave_intel()`, `core_overdraft()`, and `overload_tower()`. Do not use legacy `demolish_tower()` for GUI sales. Keep gameplay rules and calculations in the core, catch rejected commands' `ValueError`, and do not automatically start the next night after settlement.
- If the snapshot lacks data needed by an interface feature, report the missing field or event, the affected feature, and a suggested addition to the snapshot contract. Do not bypass the contract or edit the core implementation. Stable IDs already support enemy inspection; exact attack animation still requires events.

## Branches and commits

- Work on a feature branch. Do not commit directly to `main`.
- Follow existing repository code style and commit conventions. If no commit format is established, use a short, clear message such as `feat(gui): add build preview`, `fix(gui): show build errors`, or `docs(gui): add agent instructions`.
- Make one commit per completed feature or focused fix. Stage only files related to that change under `gui`; do not mix unrelated work.
- Check the diff and run relevant available checks before committing.
- When pushing a branch, include a brief English comment summarizing the pushed changes in the push report. Git push has no separate comment field.
