from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from external.clients.bot_api.models import BotMetadata
from external.contracts.base_bot import BaseBot


class BotLoaderError(RuntimeError):
    """Raised when a bot module fails discovery or validation."""


@dataclass(frozen=True)
class BotDescriptor:
    bot_id: str
    metadata: BotMetadata
    bot_class: type[BaseBot]
    module_name: str
    module_path: str


class BotLoader:
    def __init__(self, bots_dir: Path | None = None, package_name: str = "external.bots") -> None:
        self.package_name = package_name
        self.bots_dir = bots_dir or Path(__file__).resolve().parents[2] / "bots"
        self._descriptors: dict[str, BotDescriptor] | None = None

    def load_bots(self) -> dict[str, BotDescriptor]:
        if self._descriptors is not None:
            return dict(self._descriptors)

        descriptors: dict[str, BotDescriptor] = {}
        canonical_paths: dict[Path, str] = {}

        for module_path in sorted(self.bots_dir.glob("*.py")):
            if module_path.name == "__init__.py":
                continue

            resolved_path = module_path.resolve()
            if resolved_path in canonical_paths:
                original_name = canonical_paths[resolved_path]
                raise BotLoaderError(
                    f"[{module_path.name}] Duplicate canonical module path detected for "
                    f"'{original_name}' and '{module_path.stem}'."
                )
            canonical_paths[resolved_path] = module_path.stem

            descriptor = self._load_bot_descriptor(module_path)
            if descriptor.bot_id in descriptors:
                existing_path = Path(descriptors[descriptor.bot_id].module_path).name
                raise BotLoaderError(
                    f"[{module_path.name}] Duplicate BOT_META['id'] '{descriptor.bot_id}' also defined in "
                    f"'{existing_path}'."
                )
            descriptors[descriptor.bot_id] = descriptor

        self._descriptors = descriptors
        return dict(descriptors)

    @staticmethod
    def sort_metadata(metadata_items: list[BotMetadata]) -> list[BotMetadata]:
        return sorted(
            metadata_items,
            key=lambda metadata: (metadata.name.casefold(), metadata.botId.casefold()),
        )

    def _load_bot_descriptor(self, module_path: Path) -> BotDescriptor:
        module_name = f"{self.package_name}.{module_path.stem}"
        module = importlib.import_module(module_name)
        raw_meta = getattr(module, "BOT_META", None)
        if raw_meta is None:
            raise BotLoaderError(f"[{module_path.name}] Missing required BOT_META.")

        try:
            metadata = BotMetadata.from_module_meta(raw_meta)
        except ValueError as exc:
            raise BotLoaderError(f"[{module_path.name}] {exc}") from exc

        bot_class = self._extract_bot_class(module, module_path)
        class_meta = getattr(bot_class, "META", None)
        if class_meta != raw_meta:
            raise BotLoaderError(f"[{module_path.name}] {bot_class.__name__} must define META = BOT_META.")

        return BotDescriptor(
            bot_id=metadata.botId,
            metadata=metadata,
            bot_class=bot_class,
            module_name=module_name,
            module_path=str(module_path.resolve()),
        )

    @staticmethod
    def _extract_bot_class(module: ModuleType, module_path: Path) -> type[BaseBot]:
        bot_classes = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, BaseBot)
            and obj is not BaseBot
            and obj.__module__ == module.__name__
            and not inspect.isabstract(obj)
        ]

        if not bot_classes:
            raise BotLoaderError(f"[{module_path.name}] Missing concrete BaseBot subclass.")
        if len(bot_classes) > 1:
            class_names = ", ".join(sorted(bot_class.__name__ for bot_class in bot_classes))
            raise BotLoaderError(
                f"[{module_path.name}] Expected exactly one concrete BaseBot subclass, found: {class_names}."
            )
        return bot_classes[0]
