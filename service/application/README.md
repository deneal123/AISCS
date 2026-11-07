# Simulation application services

- `field/` coordinates field calculations and graph projections.
- `population/` runs independent physical source cells and their graph response.
- `feedback/` maps, schedules and iterates the coupled feedback calculation.
- `replay/` replays recorded inputs and produces derived recordings.
- `screening/` selects candidate sources for subsequent physical checks.

Model contracts live in `service/domain/contracts/`; numerical kernels and
storage adapters remain in `service/infrastructure/`. The feedback calculation
is experimental and its physical recording covers selected cells only.
