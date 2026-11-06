import ast
import logging
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


SOURCE = Path(__file__).resolve().parents[1] / "custom_components/thermostat_timeline/__init__.py"


class _FakeDtUtil:
    @staticmethod
    def utcnow():
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


class RoomPauseControlTests(unittest.IsolatedAsyncioTestCase):
    def _load_handler(self, hass, save_counter):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        setup_fn = next(
            n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry"
        )
        needed = {
            "_service_entity_ids",
            "_resolve_primary_for_room_pause",
            "_room_pause_key_for_entity",
            "_room_pause_resume_keys",
            "room_pause_control",
        }
        selected = [
            n
            for n in setup_fn.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in needed
        ]
        self.assertEqual({n.name for n in selected}, needed)

        async def _save_and_broadcast():
            save_counter["count"] += 1

        def _norm_instance_id(raw: Any) -> str:
            s = str(raw or "").strip()
            return s or "default"

        def _ensure_instances_loaded(hass_obj):
            data = hass_obj.data.setdefault("thermostat_timeline", {})
            data.setdefault("instances", {"default": {"schedules": {}, "settings": {}}})
            data.setdefault("active_instance_id", "default")

        glob = {
            "Any": Any,
            "ServiceCall": object,
            "hass": hass,
            "_save_and_broadcast": _save_and_broadcast,
            "_norm_instance_id": _norm_instance_id,
            "_ensure_instances_loaded": _ensure_instances_loaded,
            "dt_util": _FakeDtUtil,
            "DOMAIN": "thermostat_timeline",
            "_LOGGER": logging.getLogger(__name__),
        }
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), glob)
        return glob["room_pause_control"]

    def _make_hass(self, settings=None, schedules=None, instance_id="default"):
        if settings is None:
            settings = {}
        if schedules is None:
            schedules = {}
        inst = {
            "schedules": schedules,
            "settings": settings,
            "weekdays": {},
            "profiles": {},
            "colors": {},
        }
        return SimpleNamespace(
            data={
                "thermostat_timeline": {
                    "instances": {instance_id: inst},
                    "active_instance_id": instance_id,
                    "settings": settings,
                    "version": 1,
                    "settings_version": 1,
                }
            }
        )

    async def test_pause_minutes_for_merged_entity_writes_primary_key(self):
        settings = {"merges": {"climate.main": ["climate.child"]}, "room_pause": {}}
        schedules = {"climate.main": {"defaultTemp": 20, "blocks": []}}
        hass = self._make_hass(settings=settings, schedules=schedules)
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"entity_id": ["climate.child"], "minutes": 30})
        await handler(call)

        rp = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]["room_pause"]
        self.assertIn("climate.main", rp)
        self.assertFalse(rp["climate.main"]["indef"])
        self.assertGreater(rp["climate.main"]["until_ms"], 0)
        self.assertEqual(save_counter["count"], 1)
        self.assertEqual(hass.data["thermostat_timeline"]["version"], 2)
        self.assertEqual(hass.data["thermostat_timeline"]["settings_version"], 2)

    async def test_pause_with_minutes_and_indefinite_is_rejected(self):
        settings = {"room_pause": {}}
        schedules = {"climate.main": {"defaultTemp": 20, "blocks": []}}
        hass = self._make_hass(settings=settings, schedules=schedules)
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"entity_id": ["climate.main"], "minutes": 10, "indefinite": True})
        await handler(call)

        rp = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]["room_pause"]
        self.assertEqual(rp, {})
        self.assertEqual(save_counter["count"], 0)
        self.assertEqual(hass.data["thermostat_timeline"]["version"], 1)

    async def test_skips_unknown_entities_and_processes_valid_ones(self):
        settings = {"room_pause": {}}
        schedules = {"climate.main": {"defaultTemp": 20, "blocks": []}}
        hass = self._make_hass(settings=settings, schedules=schedules)
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(
            data={
                "entity_id": ["climate.unknown", "climate.main"],
                "minutes": 15,
            }
        )
        await handler(call)

        rp = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]["room_pause"]
        self.assertIn("climate.main", rp)
        self.assertEqual(len(rp), 1)
        self.assertEqual(save_counter["count"], 1)

    async def test_pause_indefinite(self):
        settings = {"room_pause": {}}
        schedules = {"climate.main": {"defaultTemp": 20, "blocks": []}}
        hass = self._make_hass(settings=settings, schedules=schedules)
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"entity_id": ["climate.main"], "indefinite": True})
        await handler(call)

        rp = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]["room_pause"]
        self.assertIn("climate.main", rp)
        self.assertTrue(rp["climate.main"]["indef"])
        self.assertEqual(rp["climate.main"]["until_ms"], 0)
        self.assertEqual(save_counter["count"], 1)


class ApplyEnabledControlTests(unittest.IsolatedAsyncioTestCase):
    def _load_handler(self, hass, save_counter):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        setup_fn = next(
            n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry"
        )
        needed = {
            "_service_entity_ids",
            "_resolve_primary_for_room_pause",
            "apply_enabled_control",
        }
        selected = [
            n
            for n in setup_fn.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in needed
        ]
        self.assertEqual({n.name for n in selected}, needed)

        async def _save_and_broadcast():
            save_counter["count"] += 1

        def _norm_instance_id(raw: Any) -> str:
            s = str(raw or "").strip()
            return s or "default"

        def _ensure_instances_loaded(hass_obj):
            data = hass_obj.data.setdefault("thermostat_timeline", {})
            data.setdefault("instances", {"default": {"schedules": {}, "settings": {}}})
            data.setdefault("active_instance_id", "default")

        glob = {
            "Any": Any,
            "ServiceCall": object,
            "hass": hass,
            "_save_and_broadcast": _save_and_broadcast,
            "_norm_instance_id": _norm_instance_id,
            "_ensure_instances_loaded": _ensure_instances_loaded,
            "DOMAIN": "thermostat_timeline",
            "_LOGGER": logging.getLogger(__name__),
        }
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), glob)
        return glob["apply_enabled_control"]

    def _make_hass(self, settings=None, schedules=None, instance_id="default"):
        if settings is None:
            settings = {}
        if schedules is None:
            schedules = {}
        inst = {
            "schedules": schedules,
            "settings": settings,
            "weekdays": {},
            "profiles": {},
            "colors": {},
        }
        return SimpleNamespace(
            data={
                "thermostat_timeline": {
                    "instances": {instance_id: inst},
                    "active_instance_id": instance_id,
                    "settings": settings,
                    "version": 1,
                    "settings_version": 1,
                }
            }
        )

    async def test_disable_for_merged_child_writes_primary(self):
        settings = {"merges": {"climate.main": ["climate.child"]}, "apply_enabled": {}}
        schedules = {"climate.main": {"defaultTemp": 20, "blocks": []}}
        hass = self._make_hass(settings=settings, schedules=schedules)
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"action": "disable", "entity_id": ["climate.child"]})
        await handler(call)

        ae = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]["apply_enabled"]
        self.assertIn("climate.main", ae)
        self.assertFalse(ae["climate.main"])
        self.assertEqual(save_counter["count"], 1)

    async def test_enable_turns_true(self):
        settings = {"apply_enabled": {"climate.main": False}}
        schedules = {"climate.main": {"defaultTemp": 20, "blocks": []}}
        hass = self._make_hass(settings=settings, schedules=schedules)
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"action": "enable", "entity_id": ["climate.main"]})
        await handler(call)

        ae = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]["apply_enabled"]
        self.assertTrue(ae["climate.main"])
        self.assertEqual(save_counter["count"], 1)

    async def test_toggle_flips_value(self):
        settings = {"apply_enabled": {"climate.main": True}}
        schedules = {"climate.main": {"defaultTemp": 20, "blocks": []}}
        hass = self._make_hass(settings=settings, schedules=schedules)
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"action": "toggle", "entity_id": ["climate.main"]})
        await handler(call)

        ae = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]["apply_enabled"]
        self.assertFalse(ae["climate.main"])
        self.assertEqual(save_counter["count"], 1)

    async def test_unknown_entity_is_skipped(self):
        settings = {"apply_enabled": {}}
        schedules = {"climate.main": {"defaultTemp": 20, "blocks": []}}
        hass = self._make_hass(settings=settings, schedules=schedules)
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"action": "disable", "entity_id": ["climate.unknown"]})
        await handler(call)

        ae = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]["apply_enabled"]
        self.assertEqual(ae, {})
        self.assertEqual(save_counter["count"], 0)


class ManualOverrideControlTests(unittest.IsolatedAsyncioTestCase):
    def _load_handler(self, hass, save_counter):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        setup_fn = next(
            n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry"
        )
        needed = {"manual_override_control"}
        selected = [
            n
            for n in setup_fn.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in needed
        ]
        self.assertEqual({n.name for n in selected}, needed)

        async def _save_and_broadcast():
            save_counter["count"] += 1

        def _norm_instance_id(raw: Any) -> str:
            s = str(raw or "").strip()
            return s or "default"

        def _ensure_instances_loaded(hass_obj):
            data = hass_obj.data.setdefault("thermostat_timeline", {})
            data.setdefault("instances", {"default": {"schedules": {}, "settings": {}}})
            data.setdefault("active_instance_id", "default")

        glob = {
            "Any": Any,
            "ServiceCall": object,
            "hass": hass,
            "_save_and_broadcast": _save_and_broadcast,
            "_norm_instance_id": _norm_instance_id,
            "_ensure_instances_loaded": _ensure_instances_loaded,
            "DOMAIN": "thermostat_timeline",
            "_LOGGER": logging.getLogger(__name__),
        }
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), glob)
        return glob["manual_override_control"]

    def _make_hass(self, settings=None, schedules=None, instance_id="default"):
        if settings is None:
            settings = {}
        if schedules is None:
            schedules = {}
        inst = {
            "schedules": schedules,
            "settings": settings,
            "weekdays": {},
            "profiles": {},
            "colors": {},
        }
        return SimpleNamespace(
            data={
                "thermostat_timeline": {
                    "instances": {instance_id: inst},
                    "active_instance_id": instance_id,
                    "settings": settings,
                    "version": 1,
                    "settings_version": 1,
                }
            }
        )

    async def test_enable_and_update_settings(self):
        hass = self._make_hass(settings={})
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"action": "enable", "minutes": 75, "threshold_c": 0.4, "mode": "contextless"})
        await handler(call)

        st = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]
        self.assertTrue(st["manual_override_enabled"])
        self.assertEqual(st["manual_override_minutes"], 75)
        self.assertAlmostEqual(st["manual_override_threshold_c"], 0.4)
        self.assertEqual(st["manual_override_mode"], "contextless")
        self.assertEqual(save_counter["count"], 1)

    async def test_disable_action(self):
        hass = self._make_hass(settings={"manual_override_enabled": True})
        save_counter = {"count": 0}
        handler = self._load_handler(hass, save_counter)

        call = SimpleNamespace(data={"action": "disable"})
        await handler(call)

        st = hass.data["thermostat_timeline"]["instances"]["default"]["settings"]
        self.assertFalse(st["manual_override_enabled"])
        self.assertEqual(save_counter["count"], 1)


if __name__ == "__main__":
    unittest.main()
