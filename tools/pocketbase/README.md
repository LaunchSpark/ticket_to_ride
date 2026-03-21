# PocketBase Local Install

Place the PocketBase Windows binary at `tools/pocketbase/pocketbase.exe`.

`uv run run` will look here automatically before falling back to `POCKETBASE_BINARY` or `PATH`.

On first local launch, the runtime will also ensure a default PocketBase superuser:

- email: `admin@example.com`
- password: `12345678`
