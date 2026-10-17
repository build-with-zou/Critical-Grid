# GUI Agent Instructions

These instructions apply to work on the Critical-Grid GUI.

## Project design overview

- Critical Grid is a top-down, 2D, pausable real-time tower defense and resource-management game. The player commands a frontier base, plans construction during the day, and responds to enemy attacks at night. The core is the objective to protect.
- The central decisions are how to spend gold, build a connected power grid, and balance economic growth against immediate defense. Power shortages reduce building effectiveness. Emergency options such as core overdraft and tower overload provide short-term help at a future cost through debt or repair pressure.
- The V0.2 design target includes eight night waves, construction and repair, power-grid disruption, time controls, and clear victory or defeat. The current prototype has four waves and only part of that ruleset; treat the code as the behavior source of truth and the design document as the target.
- The interface should use a central map, a persistent resource and status HUD, and a selection/details panel. Show gold, power supply and demand, efficiency, debt, core health, phase, wave, speed, and pause state where supported by the current snapshot. Make placement validity, power loss, damaged buildings, enemy threats, and failed actions understandable. Use text or symbols in addition to color for important states.
- The intended visual style is minimal and legible, like an engineering control console. Keep the map visible while menus and details are open. Prefer clear feedback and explainable failures over decorative effects.
- All player-facing text in the game must be in English, including menus, buttons, HUD labels, prompts, status messages, and errors shown by the GUI.
- Team ownership: the collaborator develops core game rules in `grid_td`; this developer develops interaction and presentation in `gui`, using Python, Pygame, and pygame_gui. `GameState` owns authoritative gameplay state. The GUI displays snapshots and sends commands through public methods.
- Before implementing a design feature, compare the V0.2 design document (`GAME_DESIGN(3).md`, 2026-10-11) with the current code and snapshot contract. The document is external to this repository. If it is unavailable, use this overview and report any missing design detail or core API needed for the task.

## Current core rules (verified against `grid_td` on 2026-10-16)

- `GameState` owns gold, debt, core HP, buildings, enemies, waves, and the authoritative logical clock. A new game starts in `GamePhase.DAY`; `step(seconds)` does not advance time during DAY. The player calls `start_next_wave()` to enter NIGHT. Pause is a frontend choice to withhold steps, not a core phase.
- During NIGHT, `step(seconds)` spawns due enemies, recalculates power, lets towers attack, and moves enemies. `waiting_for_next_wave` becomes true only after all enemies have spawned and the board is clear. `end_wave()` then settles income, interest, and repair markers and returns to DAY. Final settlement records VICTORY; core HP reaching zero records DEFEAT. The demo has one fixed map and four configured waves.
- The demo map is 36 by 21 small cells. Each former map tile was subdivided into 3 by 3 cells; one small cell spans one world unit. `Position` names an integer cell, while `WorldPosition` names a continuous point. Current buildings, including the core, occupy 3 by 3 cells; `Building.position` is the top-left anchor. Custom footprints are supported by the core.
- `GridMap.road_cells` is fixed road terrain, while `GridMap.path` follows fixed centerline waypoints. Enemy `path_progress` is physical distance along that path, not a waypoint index. Combat measures Manhattan world distance from a building's geometric center to an enemy's continuous world position. Towers target the furthest-progressing living enemy within range.
- `preview_build(kind, anchor)` checks the same whole-footprint terrain, occupancy, mine-site, gold, and terminal-state rules as `build()` without mutation. Ordinary placement failures return `BuildPreview.is_valid=False` and a reason; malformed inputs raise `ValueError`. Only mines fit on mine terrain, and a tower gets its high-ground range bonus only when its full footprint is on high ground. `build()` rechecks before charging gold.
- Power uses four-neighbor contact between occupied building cells, starting at the core. Partial shared edges connect; diagonal contact and empty gaps do not. Only connected buildings contribute supply/demand. All connected consumers share one efficiency: 100% with sufficient supply, at least 30% with positive shortage, and 0% when disconnected. There is no priority allocation in the current core.
- The core supplies 10 power and starts at 30 HP; the player starts with 180 gold. Kills pay immediately. Mines pay at wave settlement according to efficiency; settlement also charges 12% interest on total debt and 5 gold per repair marker. `core_overdraft()` defaults to +40 gold with 1.35-times debt; `overload_tower()` defaults to 8 logical seconds, adds 10 debt, boosts damage and attack speed, and marks the tower for settlement repair.
- The current roster has a mine, power plant, power node, and gun, cannon, and slow towers; enemy templates are Basic, Fast, Armored, and Saboteur. The slow tower applies a fixed two-second slow. Despite their names, cannon shots are currently single-target, Armored has extra HP rather than damage reduction, and Saboteur follows the ordinary fixed route without attacking infrastructure.

## Design gaps in the current core

- **Routing and map variety:** There is no path search or rerouting, building-based road blocking, route-change preview, or multi-map campaign. Construction on fixed road cells is prohibited. The V0.2 eight-night progression is represented by only four demo waves.
- **Building lifecycle:** Non-core building `hp` always equals `max_hp`; enemies cannot damage or destroy buildings. There is no build timer, upgrade, active repair command or repair progress. An overload only sets a repair marker that costs gold at settlement; it does not repair actual damage. Power-grid disruption from building damage therefore does not occur.
- **Combat behaviors:** Cannon splash, armor damage reduction, Saboteur target selection and infrastructure attacks, and player-assigned tower targets are absent. The default tower target is highest route progress; there is no manual-target command.
- **Power and economy:** The core implements edge-adjacent power, while the design document proposes a radius-based network. Per-building supply priority, damaged-grid efficiency, debt repayment, debt-source breakdown, and a base reward per wave are absent. These are design decisions/core changes, not GUI calculations.
- **Intelligence and command rules:** `buy_wave_intel()` spends 8 gold for one briefing string; there is no structured free forecast or detailed counts, order, targets, and timing as described in V0.2. Build and intel commands currently allow both DAY and NIGHT, while the design leaves some night restrictions undecided. `demolish_tower()` has no terminal-phase rejection in the core; do not assume every command shares the same phase guard.
- **Time and campaign rules:** The core accepts logical step durations but has no stored speed multiplier or bullet-time state. The frontend can pause by withholding steps; slowdown/acceleration policy is not established. Scoring and additional victory/failure conditions beyond final-wave survival and core destruction are absent.
- **Presentation events:** Snapshots do not expose stable enemy IDs, tower attack/damage events, enemy targets, or an authoritative route preview. Exact attack-beam animation, enemy tracking across frames, target indicators, and route-change previews need new snapshot fields/events; do not reconstruct them from mutable entities or waypoint indices.

## Current GUI coverage

- The GUI now fits the 36-by-21 map, draws building footprints and continuous enemy positions from snapshots, uses `preview_build()` for hover feedback, and returns to DAY after each settled night. It provides Start Night, Run/Pause, one-second stepping, building placement, tower demolition, and keyboard tower overload.
- `buy_wave_intel()` and `core_overdraft()` exist in the core but have no GUI controls yet. This is a presentation gap, distinct from the missing structured intelligence and debt rules above.
- The GUI draws enemies at short fixed logical steps rather than reconstructing attacks from mutable objects. Accurate attack beams and persistent enemy interpolation remain blocked by the missing snapshot IDs/events noted above.

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
- Perform gameplay actions through public `GameState` commands: `start_next_wave()`, `step()`, `end_wave()`, `preview_build()`, `build()`, `demolish_tower()`, `buy_wave_intel()`, `core_overdraft()`, and `overload_tower()`. Keep gameplay rules and calculations in the core, catch rejected commands' `ValueError`, and do not automatically start the next night after settlement.
- If the snapshot lacks data needed by an interface feature, report the missing field or event, the affected feature, and a suggested addition to the snapshot contract. Do not bypass the contract or edit the core implementation. This also applies to stable IDs or events needed for animation.

## Branches and commits

- Work on a feature branch. Do not commit directly to `main`.
- Follow existing repository code style and commit conventions. If no commit format is established, use a short, clear message such as `feat(gui): add build preview`, `fix(gui): show build errors`, or `docs(gui): add agent instructions`.
- Make one commit per completed feature or focused fix. Stage only files related to that change under `gui`; do not mix unrelated work.
- Check the diff and run relevant available checks before committing.
- When pushing a branch, include a brief English comment summarizing the pushed changes in the push report. Git push has no separate comment field.
