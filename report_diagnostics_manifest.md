YJ-64 — PROTECTED-LINE-GUARD

ЕДИНЫЙ КОНТРОЛЬНЫЙ ФАЙЛ И УПРАВЛЕНИЕ ИЗМЕНЕНИЯМИ

============================================================
РАЗДЕЛ 1. ОБЯЗАТЕЛЬНЫЙ ПОРЯДОК РАБОТЫ

НАЗНАЧЕНИЕ:
Guard — единственный источник разрешённых изменений защищённых
рабочих участков и обязательная контрольная точка перед Android Build.

ПОРЯДОК:
1. Определить рабочие файлы и точные участки, которые требуется изменить.
2. Показать владельцу план и получить явное согласование.
3. Скопировать точный исходный фрагмент рабочего файла на операционный стол.
4. Изменять только копию на операционном столе.
5. Перед переносом подтвердить, что исходный фрагмент встречается ровно один раз.
6. Заменить только согласованный участок и проверить уникальность нового фрагмента.
7. Проверить отсутствие изменений за пределами согласованного участка.
8. Обновить контрольные Git blob SHA по фактическим рабочим файлам.
9. Запустить Guard Validation; Android Build разрешён только после PASS.
10. После завершения переноса удалить патч с операционного стола.

ОГРАНИЧЕНИЯ:
- Исходный код копируется из рабочего файла, не восстанавливается по памяти.
- Пробелы, отступы и переводы строк считаются частью фрагмента.
- Наличие задачи в очереди не является разрешением на её реализацию.
- Успешная компиляция не заменяет Guard Validation.
- При несовпадении исходного фрагмента перенос прекращается; автоматическая
  подмена или расширение области изменения запрещены.

ФОРМАТ ЗАЩИЩЁННОГО ФРАГМЕНТА: в разделе 2 используется запись
`FILE: путь/к/файлу BEGIN ALLOWED` с точным исходным кодом и завершающей
строкой `END ALLOWED`. Этот формат не применяется на операционном столе;
там используются поля TARGET FILE / ORIGINAL FRAGMENT / NEW FRAGMENT.

============================================================
РАЗДЕЛ 2. ЗАЩИЩЁННЫЕ ФРАГМЕНТЫ

Назначение:

В этом разделе находятся точные фрагменты рабочего кода,
которые проверяются на сохранность.

FILE: main.py BEGIN ALLOWED
        actions = [
            ("СОЗДАТЬ АРХИВ В ЗАГРУЗКАХ", self._auto_export_download_archive),
            ("СОЗДАТЬ АРХИВ ВЫБОРОМ ПАПКИ", self._create_memory_archive),
            ("ВОССТАНОВИТЬ ИЗ ZIP", self._choose_memory_archive),
            ("ЭКСПОРТ ЛИЧНЫХ АРХИВОВ (ШИФРОВАНИЕ)", self._open_private_archive_export),
            ("ВОССТАНОВИТЬ ЛИЧНЫЕ АРХИВЫ", self._open_private_archive_import),
            ("НАСТРОЙКИ ЧАТА: ШРИФТ И ИМЕНА", self._open_chat_appearance_settings),
            (self._t(5), self._open_tools_menu),
            (self._t(6), self._show_chats),
            (self._t(7), self._new_chat),
            (self._t(11), self._open_skills_editor),
        ]
END ALLOWED

FILE: main.py BEGIN ALLOWED
            self._append_report("memory_archive_batch_completed",
                                successful=len(results), failed=len(failures),
                                results=results, failures=failures,
                                all_archives_verified=bool(results) and not failures)
END ALLOWED

FILE: chat_workspace.py BEGIN ALLOWED
    def __init__(self, user_data_dir: str | Path):
        self.root = Path(user_data_dir) / "yj64-workspace"
        self.root.mkdir(parents=True, exist_ok=True)
        self.chats_dir = self.root / "chats"
        self.agents_dir = self.root / "agents"
        self.histories_dir = self.root / "histories"
        for folder in (self.chats_dir, self.agents_dir, self.histories_dir):
            folder.mkdir(parents=True, exist_ok=True)
        self.skills_path = self.root / "skills.md"
        if not self.skills_path.exists():
            self.skills_path.write_text("# YJ-64 local skills\n", encoding="utf-8")
        self.index_path = self.root / "chats.json"
        if not self.index_path.exists():
            self._write_json(self.index_path, {"chats": []})
        if not self.list_chats():
            self.create_chat("Общий чат")
        self.ensure_chat_files()

    def ensure_chat_files(self) -> None:
        """Create missing chat histories without overwriting existing files."""
        for chat in self.list_chats():
            chat_id = str(chat.get("id", "")).strip()
            if not chat_id:
                continue
            path = self._messages_path(chat_id)
            if not path.exists():
                self._write_json(path, [])
END ALLOWED

============================================================

============================================================
РАЗДЕЛ 3. НЕИЗМЕНЯЕМЫЕ УЧАСТКИ

Рабочие участки, не включённые в согласованный патч, не изменяются.
Если требуется затронуть новый участок, он сначала точно копируется
на операционный стол и получает отдельный PATCH-ID.
Прямое редактирование такого участка без этого порядка запрещено.

============================================================
РАЗДЕЛ 4. ОПЕРАЦИОННЫЙ СТОЛ

СТАТУС: CLEAN — НЕТ АКТИВНЫХ ПАТЧЕЙ.

На операционном столе нет незавершённых изменений.
Новые изменения помещаются сюда только после отдельного согласования
и копирования точных исходных фрагментов из рабочих файлов.

Нерешённые задачи и порядок их выполнения находятся в очереди
в последнем разделе этого файла.

============================================================

РАЗДЕЛ 5. ПРОВЕРКА ПЕРЕНОСА

Для каждого активного патча:
1. Проверить единственность ORIGINAL FRAGMENT в рабочем файле.
2. Проверить NEW FRAGMENT и его отступы.
3. Выполнить только согласованную замену.
4. Проверить единственность нового фрагмента и отсутствие побочных изменений.
5. Обновить SHA изменённых рабочих файлов.
6. Запустить tools/verify_guard.py и добиться успешного результата.

Если любой шаг не пройден, перенос считается незавершённым.
Сборка до успешной проверки Guard запрещена.

============================================================
РАЗДЕЛ 6. ОЧЕРЕДЬ ЗАДАЧ

Очередь перенесена в последний раздел файла, после всех implementation
records и контрольных данных. См. «ФИНАЛЬНАЯ ОЧЕРЕДЬ РЕШЕНИЯ ЗАДАЧ».

============================================================

РАЗДЕЛ 7. КОНТРОЛЬНЫЕ ДАННЫЕ РАБОЧИХ ФАЙЛОВ

Контрольные значения — Git blob SHA-1.

После каждого согласованного переноса изменения в рабочие файлы
контрольные SHA должны быть обновлены по фактическому содержимому.

============================================================

============================================================
КОНЕЦ PROTECTED-LINE-GUARD

============================================================
ЗАМЕТКА О ПЕРЕНОСЕ — YJ64-REMOTE-RENAME-RESTORED-CONTEXT-002
Все изменения PATCH 002-A—002-F обнаружены в текущем рабочем main.py:
- защищённая загрузка remote_participant;
- переименование участника и отображаемые имена;
- отдельный restored-model-context.json;
- восстановление ZIP без добавления архива в видимую историю;
- передача восстановленного контекста в общий и личный запросы.
Подробный implementation record и проверки сохранены ниже.
Повторно в операционном столе эти фрагменты не держать.
============================================================

============================================================
PATCH IMPLEMENTATION RECORD — YJ64-REMOTE-RENAME-RESTORED-CONTEXT-002
APPROVED BY OWNER: 2026-10-31
TARGET: main.py; buildozer.spec; .github/workflows/android-apk.yml
VERSION: 0.1.34

EXACT ORIGINAL FRAGMENTS VERIFIED AGAINST WORKING BRANCH BEFORE EDIT:
- _open_remote_participant(): exact import/client initialization block.
- _open_chat_appearance_settings(): complete method; remove legacy participant-name fields because rename moves to participant menu.
- _participant_label(): insert custom-name precedence before localized default labels.
- _open_participant_menu(): insert rename action after participant title.
- build(): workspace initialization and common-history load.
- _on_archive_activity_result(): complete existing import branch.
- private participant send_message(): common/private history construction.
- _send_llm_chat(): per-participant history_snapshot loop.

IMPLEMENTATION DETAILS:
1. REMOTE import is wrapped in try/except; failure is reported and shown in a popup without crashing the base app. remote_participant.py itself is absent from this branch and is NOT created by this patch.
2. Participant rename is moved from global appearance settings into each participant menu. _participant_label() now prioritizes saved display names, so participant buttons reflect the change. Font settings retain stored names.
3. Restored common archive messages are stored in yj64-workspace/restored-model-context.json, separately from common_history. Existing restored context is merged with messages from every archived common chat; stable message IDs (or legacy content hashes) deduplicate entries; timestamp ordering is retained.
4. Import creates a fresh visible chat and sets common_history to empty. Archived content is never copied into the visible transcript.
5. Restored common context is included in general participant model requests and private participant requests. Participant-specific private histories remain separate and are appended only to that participant's request.
6. Private agent records under agents/*.json are not flattened into common restored context. Their private_messages remain separate.
7. The context file is inside yj64-workspace and is therefore included by PersistentCore._collect_files() in subsequent archives.
8. buildozer.spec version is raised from 0.1.32 to 0.1.33. Android workflow names the APK YJ-64-Base-v0.1.33-arm64-v8a-debug.apk and artifact yj64-base-v0.1.33-apk.

ACCEPTANCE CHECKS REQUIRED:
- Python compile and Guard Validation PASS before Android build.
- Verify no restored messages appear in common_history or chat_output after import.
- Verify Participant 1/2 each answer from restored context.
- Verify context survives restart and a second archive/export/import cycle.
- Verify custom participant labels persist after restart and appear on participant buttons.
- Verify missing remote_participant import opens error popup and app remains usable.

STATUS: IMPLEMENTED IN WORKING FILES; VALIDATION PENDING.
============================================================

IMPLEMENTATION RECORD — YJ64-PRIVATE-CHAT-ARCHIVE-001
APPROVED BY OWNER: 2026-10-31
WORKING FILES UPDATED ON APPROVED BRANCH:
- yj64_persistent_core.py — blob bf7bfffb6e0063ce09690c32146280c368b3cac8
- main.py — blob b3651dc053ee29ed099483cde2624bf7c87b72a4
- chat_workspace.py — blob 41201f85eeb892be09dd22c8b838e0195ba0cc1b

IMPLEMENTED:
1. Common archive collection excludes yj64-workspace/histories/**.
2. Existing accumulated common archive state removes legacy histories/** entries before writing the next common archive.
3. PersistentCore.export_private_archives() creates separate ZIP files grouped by participant from named private histories and agent private_messages; source files are not mutated.
4. Private ZIPs include a schema/participant manifest and SHA-256/size metadata, and are checked with ZIP integrity and member-list validation before acceptance.
5. Main automatic export creates the common archive and all private archives, publishes each to Download/YJ-64 using MediaStore, reads each published file back and verifies byte count, SHA-256 and ZIP integrity.
6. Each archive publication reports success or failure independently; batch PASS is withheld if any archive failed.
7. New agent private messages receive message_id, timestamp, timestamp_ms, session_id, participant_id and message_type metadata.
8. Private archives are plaintext ZIPs. Cryptographic encryption/key management is NOT implemented.

KNOWN LIMITATIONS / REQUIRED FOLLOW-UP:
- Private ZIP restore is not yet wired into the archive picker; common importer must not be used for private ZIPs. A separate explicit, identity-checked restore flow remains required.
- Existing legacy private agent messages retain their original fields; exporter preserves them without fabricating historical IDs/timestamps.
- Validate grouping for agents whose runner values differ from canonical participant labels.
- Device-level MediaStore operation, file-manager visibility and failure paths require Android runtime testing.
- Private archive ZIPs group histories by filename and agent records by runner. This is not encryption or an access-control boundary after a user copies the ZIP.

STATUS: PRIVATE CHAT ARCHIVE IMPLEMENTED; PRIVACY DIAGNOSTICS PATCH ADDED; GUARD/CI VALIDATION PENDING.

============================================================
PATCH-ID: YJ64-PRIVACY-DIAGNOSTICS-001
STATUS: IMPLEMENTED — GUARD/CI VALIDATION REQUIRED

SCOPE:
- Replace raw diagnostic payloads with allowlisted operational metadata.
- Store only sanitized data in JSONL and SQLite.
- Migrate existing local SQLite event rows to remove legacy payload text.
- Exclude diagnostic JSONL and private history files from common archives.
- Replace the repository's real diagnostic sample with synthetic metadata.
- Add regression tests and make CI run them before Android build.

FILE: diagnostics.py BEGIN ALLOWED
"""Privacy-safe diagnostic event filtering for YJ-64.

Only bounded operational metadata is retained. Message bodies, model output,
exception text, tracebacks, credentials, and arbitrary fields are never stored.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_SAFE_STRING_FIELDS = {
    "process_name", "provider", "model", "route_id", "operation_id",
    "request_id", "error_type", "status", "archive_schema",
}
_SAFE_INTEGER_FIELDS = {
    "pid", "history_count", "common_history_count", "private_history_count",
    "prompt_length", "response_length", "input_length", "output_length",
    "file_count", "file_size", "size_bytes", "status_code", "http_status",
    "retry_count", "attempt", "elapsed_ms", "duration_ms", "line_number",
}
_SAFE_BOOLEAN_FIELDS = {
    "configured", "explicit_user_action", "focused", "success",
    "all_archives_verified", "private", "error_present",
}
_PROMPT_FIELDS = {"prompt", "message", "request", "request_message", "input", "content"}
_RESPONSE_FIELDS = {"response", "output", "result"}
_ERROR_FIELDS = {"error", "exception", "traceback", "message_error"}
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}$")
_PARTICIPANT = re.compile(r"^(Owner|Participant [1-9][0-9]*)$")


def _safe_string(field: str, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 96:
        return None
    if field == "participant":
        return value if _PARTICIPANT.fullmatch(value) else None
    if field == "mode":
        return value if value in {"text", "agent"} else None
    if field == "provider":
        return value if _SAFE_TOKEN.fullmatch(value) else None
    return value if _SAFE_TOKEN.fullmatch(value) else None


def sanitize_event_data(event: str, data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a strict metadata-only representation of an event payload."""
    if not isinstance(data, Mapping):
        return {}

    safe: dict[str, Any] = {}
    prompt_length = None
    response_length = None
    error_present = False

    for raw_key, value in data.items():
        key = str(raw_key).strip().lower()

        if key in _PROMPT_FIELDS and isinstance(value, (str, bytes, bytearray)):
            prompt_length = len(value)
            continue
        if key in _RESPONSE_FIELDS and isinstance(value, (str, bytes, bytearray)):
            response_length = len(value)
            continue
        if key in _ERROR_FIELDS:
            error_present = value is not None
            continue

        if key in _SAFE_STRING_FIELDS or key in {"participant", "mode"}:
            cleaned = _safe_string(key, value)
            if cleaned is not None:
                safe[key] = cleaned
            continue

        if key in _SAFE_INTEGER_FIELDS:
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**63 - 1:
                safe[key] = value
            continue

        if key in _SAFE_BOOLEAN_FIELDS and isinstance(value, bool):
            safe[key] = value

    if prompt_length is not None:
        safe["prompt_length"] = prompt_length
    if response_length is not None:
        safe["response_length"] = response_length
    if error_present:
        safe["error_present"] = True
    return safe
END ALLOWED

FILE: main.py BEGIN ALLOWED
    def _append_report(self, event: str, **data: Any) -> None:
        try:
            safe_data = sanitize_event_data(event, data)
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "schema": "yj64.diagnostic.v1",
                "agent": "yj64-base-application",
                "event": event,
                "timestamp_ms": int(time.time() * 1000),
                "monotonic_ns": time.monotonic_ns(),
                "message_id": f"APP-{uuid.uuid4().hex}",
                "data": safe_data,
            }
            with self.report_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                self.persistent_core.record_event(event, safe_data)
            except Exception:
                # SQLite is secondary to the primary diagnostic JSONL; never block UI.
                pass
        except OSError:
            pass
END ALLOWED

FILE: yj64_persistent_core.py BEGIN ALLOWED
    def record_event(self,event:str,data:dict[str,Any]|None=None)->None:
        safe_data = sanitize_event_data(event, data or {})
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO events(timestamp_ms,event,data_json) VALUES(?,?,?)",
                    (int(time.time()*1000), str(event), json.dumps(safe_data, ensure_ascii=False)),
                )
        except sqlite3.Error:
            return

    def _sanitize_existing_events(self) -> None:
        """Remove legacy raw message/error payloads from the local event ledger."""
        try:
            with self._connect() as db:
                rows = db.execute("SELECT id,event,data_json FROM events").fetchall()
                for row_id, event, raw_json in rows:
                    try:
                        raw_data = json.loads(raw_json)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        raw_data = {}
                    safe_data = sanitize_event_data(str(event), raw_data if isinstance(raw_data, dict) else {})
                    safe_json = json.dumps(safe_data, ensure_ascii=False)
                    if safe_json != raw_json:
                        db.execute("UPDATE events SET data_json=? WHERE id=?", (safe_json, row_id))
        except sqlite3.Error:
            return
END ALLOWED

FILE: yj64_persistent_core.py BEGIN ALLOWED
    def _collect_files(self)->dict[str,bytes]:
        result={}
        # Diagnostic JSONL can contain legacy sensitive records; never place it
        # in a common archive, even if older versions wrote raw payloads there.
        for base in (self.workspace_path,):
            if base.is_file() and not base.is_symlink():items=[base]
            elif base.is_dir() and not base.is_symlink():items=[p for p in base.rglob("*") if p.is_file() and not p.is_symlink()]
            else:items=[]
            for p in items:
                name=p.relative_to(self.root).as_posix()
                if name.startswith("yj64-workspace/histories/"):
                    continue
                if p.suffix.lower() == ".jsonl":
                    continue
                data=p.read_bytes()
                result[name]=self._sanitize_json(data) if p.suffix.lower()==".json" else data
        for pattern in ("yj64-router-config.json","yj64-llm-config*.json"):
            for p in self.root.glob(pattern):
                if p.is_file() and not p.is_symlink():result[p.name]=self._sanitize_json(p.read_bytes())
        return result
END ALLOWED

FILE: tests/test_diagnostics_privacy.py BEGIN ALLOWED
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from diagnostics import sanitize_event_data
from yj64_persistent_core import PersistentCore


class DiagnosticPrivacyTests(unittest.TestCase):
    def test_message_and_model_payloads_are_replaced_with_lengths(self):
        safe = sanitize_event_data(
            "participant_request_started",
            {
                "participant": "Participant 1",
                "route_id": "route_1",
                "mode": "text",
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "prompt": "private user message",
                "response": "private model response",
                "error": "authorization: Bearer very-secret-token",
                "traceback": "private traceback content",
                "private_history_count": 2,
            },
        )
        self.assertEqual(safe["prompt_length"], len("private user message"))
        self.assertEqual(safe["response_length"], len("private model response"))
        self.assertTrue(safe["error_present"])
        self.assertEqual(safe["private_history_count"], 2)
        for forbidden in ("prompt", "response", "error", "traceback"):
            self.assertNotIn(forbidden, safe)
        self.assertNotIn("very-secret-token", json.dumps(safe))

    def test_unknown_fields_and_custom_participant_names_are_dropped(self):
        safe = sanitize_event_data(
            "event",
            {
                "participant": "Alice Smith",
                "endpoint": "https://example.invalid/private?token=secret",
                "custom_field": "private data",
                "pid": 123,
            },
        )
        self.assertEqual(safe, {"pid": 123})

    def test_event_ledger_stores_only_sanitized_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = PersistentCore(tmp)
            core.record_event(
                "participant_api_response_received",
                {"response": "private answer", "provider": "openai", "model": "gpt-test"},
            )
            with sqlite3.connect(core.db_path) as db:
                stored = json.loads(db.execute("SELECT data_json FROM events").fetchone()[0])
            self.assertEqual(stored["response_length"], len("private answer"))
            self.assertNotIn("response", stored)
            self.assertEqual(stored["provider"], "openai")

    def test_startup_migration_scrubs_legacy_event_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "yj64-persistent-core.sqlite3"
            with sqlite3.connect(db_path) as db:
                db.execute(
                    "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp_ms INTEGER NOT NULL, event TEXT NOT NULL, data_json TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO events(timestamp_ms,event,data_json) VALUES(1,?,?)",
                    ("participant_request_started", json.dumps({"prompt": "legacy private text"})),
                )
            core = PersistentCore(tmp)
            with sqlite3.connect(core.db_path) as db:
                stored = json.loads(db.execute("SELECT data_json FROM events").fetchone()[0])
            self.assertEqual(stored["prompt_length"], len("legacy private text"))
            self.assertNotIn("prompt", stored)

    def test_common_archive_excludes_report_jsonl_and_private_histories(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = PersistentCore(tmp)
            private_dir = core.workspace_path / "histories"
            common_dir = core.workspace_path / "chats"
            private_dir.mkdir(parents=True)
            common_dir.mkdir(parents=True)
            (private_dir / "Participant 1.json").write_text(
                json.dumps([{"role": "user", "content": "private chat text"}]),
                encoding="utf-8",
            )
            (common_dir / "common.json").write_text(
                json.dumps([{"role": "user", "content": "common chat text"}]),
                encoding="utf-8",
            )
            core.report_path.parent.mkdir(parents=True, exist_ok=True)
            core.report_path.write_text(
                '{"event":"participant_request_started","data":{"prompt":"legacy private prompt"}}\n',
                encoding="utf-8",
            )
            collected = core._collect_files()
            self.assertIn("yj64-workspace/chats/common.json", collected)
            self.assertNotIn("yj64-workspace/histories/Participant 1.json", collected)
            self.assertFalse(any(name.endswith(".jsonl") for name in collected))

    def test_private_bundle_round_trip_restores_private_histories_and_agent_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = PersistentCore(Path(tmp) / "source")
            histories = source.workspace_path / "histories"
            agents = source.workspace_path / "agents"
            histories.mkdir(parents=True)
            agents.mkdir(parents=True)
            history = [{"role": "user", "content": "secret participant message"}]
            private_messages = [{"role": "assistant", "content": "private agent response"}]
            (histories / "participant_1.json").write_text(json.dumps(history), encoding="utf-8")
            (agents / "agent_1.json").write_text(json.dumps({
                "id": "agent_1", "name": "Agent One", "runner": "participant_1",
                "created_ms": 123, "private_messages": private_messages,
            }), encoding="utf-8")
            bundle = Path(tmp) / "private-bundle.zip"
            source.export_private_bundle(bundle)
            self.assertTrue(bundle.is_file())
            target = PersistentCore(Path(tmp) / "target")
            restored = target.import_private_bundle(bundle)
            self.assertEqual(restored, 2)
            self.assertEqual(
                json.loads((target.workspace_path / "histories" / "participant_1.json").read_text(encoding="utf-8")),
                history,
            )
            restored_agent = json.loads((target.workspace_path / "agents" / "agent_1.json").read_text(encoding="utf-8"))
            self.assertEqual(restored_agent["private_messages"], private_messages)

    def test_private_bundle_rejects_tampered_member_without_restoring(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            source = PersistentCore(Path(tmp) / "source")
            histories = source.workspace_path / "histories"
            histories.mkdir(parents=True)
            (histories / "participant_1.json").write_text(
                json.dumps([{"role": "user", "content": "private"}]), encoding="utf-8"
            )
            bundle = Path(tmp) / "private-bundle.zip"
            source.export_private_bundle(bundle)
            tampered = Path(tmp) / "tampered.zip"
            with zipfile.ZipFile(bundle, "r") as original, zipfile.ZipFile(tampered, "w") as changed:
                for name in original.namelist():
                    data = original.read(name)
                    if name.startswith("participants/"):
                        data += b"tampered"
                    changed.writestr(name, data)
            target = PersistentCore(Path(tmp) / "target")
            with self.assertRaises(ValueError):
                target.import_private_bundle(tampered)
            self.assertFalse((target.workspace_path / "histories" / "participant_1.json").exists())


if __name__ == "__main__":
    unittest.main()
END ALLOWED

NOTE:
Private ZIP archives remain plaintext ZIP files in this patch. Encryption and
portable password-based key management are not implemented here. Rewriting
the latest diagnostic sample does not erase earlier Git history; inspect
history separately if any credential was ever committed and rotate it.
============================================================

EXPECTED-GIT-BLOB-SHA:main.py=3f8ca98d315c9646fb099afa4e9f685f6769a018
EXPECTED-GIT-BLOB-SHA:chat_workspace.py=41201f85eeb892be09dd22c8b838e0195ba0cc1b
EXPECTED-GIT-BLOB-SHA:yj64_persistent_core.py=3921e8e553a13c99ed999d258ad66b8705bfd471
EXPECTED-GIT-BLOB-SHA:buildozer.spec=9ae2a656d9b91c81e739a389a29c4d16c7c7c92f
EXPECTED-GIT-BLOB-SHA:diagnostics.py=e768f425255e72c9f9098d9f0816b558b7e81751
EXPECTED-GIT-BLOB-SHA:tests/test_diagnostics_privacy.py=1b0aac12ab641c879ef4d93d6e9513409a604599
EXPECTED-GIT-BLOB-SHA:reports/latest-report.jsonl=ca9f1540f21dfb93aac91ad791dc2840b2d3f233

FILE: tools/verify_guard.py BEGIN ALLOWED
SECTION_RE = re.compile(
    r"^FILE: (?P<path>[^\n]+?) BEGIN ALLOWED\n(?P<content>.*?)\nEND ALLOWED$",
    re.MULTILINE | re.DOTALL,
)
END ALLOWED
EXPECTED-GIT-BLOB-SHA:tools/verify_guard.py=05604885ec0babf25fa55ea6d5343b21c7f88a7d

============================================================
ФИНАЛЬНАЯ ОЧЕРЕДЬ РЕШЕНИЯ ЗАДАЧ
============================================================

СТАТУС: 7 ФУНКЦИОНАЛЬНЫХ БЛОКОВ. АКТИВНЫХ ПАТЧЕЙ НЕТ.

Очередь организована для последовательного переноса изменений
с операционного стола в рабочие файлы:

ФУНКЦИОНАЛЬНЫЙ БЛОК
  -> небольшие логически завершённые переносы (PATCH)
  -> проверка каждого переноса
  -> общая проверка блока
  -> implementation record
  -> переход к следующему блоку.

ОБЩИЕ ПРАВИЛА ПЕРЕНОСА:
- Блок — это функциональная область работ, а не один большой патч.
- Внутри блока изменения делятся на небольшие переносы. Один перенос
  может затрагивать несколько тесно связанных файлов, если без этого
  нельзя завершить одну функцию.
- Перед каждым переносом отдельно определить точные файлы, исходные
  фрагменты и ожидаемый результат; показать владельцу и получить
  согласование.
- На операционный стол помещать только текущий согласованный PATCH,
  а не весь блок целиком.
- Исходные фрагменты копировать из актуальных рабочих файлов.
  Не восстанавливать код по памяти и не подменять несовпадающий фрагмент.
- После каждого переноса проверять точность замены и отсутствие
  изменений за пределами согласованной области.
- После завершения всех переносов блока провести его функциональные
  проверки и Guard Validation; зафиксировать результат.
- Не запускать Android Build до Guard PASS.
- Если проверка выявила ошибку, исправлять её отдельным согласованным
  PATCH внутри текущего блока. Не переходить дальше с незакрытым дефектом.
- Уже реализованный код не дублировать и без необходимости не переписывать.
- Статическое наличие кода не считать доказательством Android runtime,
  корректной криптографии, синхронизации или успешной работы на устройстве.

УЖЕ РЕАЛИЗОВАНО — НЕ СОЗДАВАТЬ ПОВТОРНО:
- Диагностическая фильтрация и allowlist метаданных в diagnostics.py.
- Очистка legacy diagnostic event rows при миграции.
- Исключение диагностического JSONL и личных histories из общего архива.
- Базовые Python export/import операции для зашифрованного private bundle.
- Java-класс android_src/PrivateArchiveCrypto.java с AES-256-GCM
  и PBKDF2-HMAC-SHA256.
- Отдельные действия экспорта и восстановления личных архивов в main.py.
- CI workflow с Guard, Python compile, privacy tests, Base APK
  и Monitor APK build steps.
- Исправление прежнего ложного вывода о дублировании participant
  в словарном вызове.

Наличие этих компонентов не означает, что все Android/runtime проверки
пройдены. Оставшиеся проверки включены в соответствующие блоки.

============================================================
БЛОК 1. ИЗОЛЯЦИЯ ДАННЫХ, ЛИЧНЫЕ АРХИВЫ И ВОССТАНОВЛЕНИЕ
============================================================

ЦЕЛЬ:
Закрыть границы доступа между участниками и довести архивный цикл
до предсказуемого, проверяемого состояния.

ЗАВИСИМОСТЬ: нет. Это первый блок.

ПЕРЕНОС 1.1 — ИДЕНТИФИКАЦИЯ УЧАСТНИКОВ
Предварительно проверить:
- Сопоставление histories/*.json с runner в agents/*.json.
- Canonical participant IDs, отображаемые имена и варианты написания.
- Пробелы, спецсимволы, конфликтующие и повторяющиеся имена.
- Существующие правила requester / owner / participant / monitor.

Вероятные файлы: yj64_persistent_core.py, chat_workspace.py,
message_distributor.py, main.py — точный список определить после аудита.
Результат: однозначное сопоставление личных данных с владельцем.

ПЕРЕНОС 1.2 — ПРОВЕРКА ГРАНИЦ ЛИЧНОГО КОНТЕКСТА
- Проверить, что личные истории и private_messages не попадают
  в архив другого участника.
- Проверить состав model request: участник получает общий контекст
  и только собственную личную историю.
- Исключить передачу чужих private histories и private agent messages
  другим участникам и Monitor.
Результат: подтверждённая изоляция контекста на уровне формирования запросов.

ПЕРЕНОС 1.3 — РЕГРЕССИОННЫЕ ТЕСТЫ И ДИАГНОСТИКА
- Добавить тесты на идентификацию, изоляцию, экспорт и импорт.
- Проверить, что диагностические события не сохраняют тексты запросов,
  ответов, исключений, traceback и секреты.
- Проверить миграцию старых diagnostic rows и исключения личных данных
  из общего архива.
Результат: тестами покрыты правила доступа и приватности.

ПЕРЕНОС 1.4 — ANDROID CRYPTO / PRIVATE BUNDLE
- Проверить включение android_src/PrivateArchiveCrypto.java
  в фактически собираемый APK и реальные вызовы из Python/Java bridge.
- Проверить AES-256-GCM, PBKDF2-HMAC-SHA256, salt, nonce,
  число итераций и совместимость encrypt/decrypt.
- Проверить на Android правильный/неверный пароль, повреждённый,
  пустой и слишком большой файл, ошибки записи и прерывание операции.
- Проверить очистку временного plaintext.
Результат: Android round-trip подтверждён на устройстве или явно отмечен
как непроверенный, если устройство недоступно.

ПЕРЕНОС 1.5 — ЕДИНЫЙ СЦЕНАРИЙ ЭКСПОРТА И ВОССТАНОВЛЕНИЯ
- Согласовать единый пользовательский сценарий общего и личных архивов,
  не объединяя их содержимое в один доступный всем архив.
- Выбрать единый согласованный путь сохранения: Download/YJ-64
  либо SAF; не смешивать несовместимые механизмы.
- Проверять запись и чтение обратно, размер, SHA-256 и целостность ZIP.
- Показывать отдельный результат каждого артефакта; общий PASS запрещён,
  если обязательный файл не сохранён или не проверен.
- Проверить повторный импорт, конфликт историй, participant ID mismatch,
  повреждение файла и неверный пароль.
- Не переписывать существующий отдельный импорт без доказанной необходимости.
Результат блока 1: проверенные границы доступа и согласованный архивный цикл.

КОНТРОЛЬ БЛОКА 1:
Python compile + privacy/archive tests + Guard Validation.
Android runtime и криптографические проверки отмечаются отдельно.
После PASS — implementation record и очистка операционного стола.

============================================================
БЛОК 2. MONITOR И МЕЖПРИЛОЖЕНЧЕСКАЯ ДИАГНОСТИКА
============================================================

ЦЕЛЬ:
Сделать Monitor самостоятельным, корректно адресованным и безопасным
получателем диагностических метаданных.

ЗАВИСИМОСТЬ: блок 1 должен подтвердить правила приватности.

ПЕРЕНОС 2.1 — КОНФИГУРАЦИЯ РЕПОЗИТОРИЯ И ВЕТКИ
- Проверить android_src/MonitorActivity.java и
  monitor-app/.../MonitorActivity.java.
- Убрать старую жёсткую привязку к test/build-diagnostic-2026-10-31.
- Вынести REPO/BRANCH в согласованную конфигурацию назначения.
- Не привязывать рабочий Monitor к main без отдельного решения.
Результат: Monitor публикует только в согласованную цель.

ПЕРЕНОС 2.2 — ПОЛИТИКА ПУБЛИКАЦИИ
- Сохранить запрет автоматической публикации при открытии Monitor.
- Публикация разрешена только после явного подтверждения пользователя.
- Передавать только очищенный диагностический отчёт.
Результат: проверяемое подтверждение перед каждой публикацией.

ПЕРЕНОС 2.3 — СОБСТВЕННЫЙ КАНАЛ СБОЕВ YJ-64
- Убрать попытку читать getHistoricalProcessExitReasons()
  другого приложения после SecurityException.
- Реализовать фиксацию сбоев самим приложением YJ-64.
- Добавить защищённый IPC, например ContentProvider
  с signature-level permission, если это подходит фактической архитектуре.
- Добавить событие незавершённой сессии при следующем запуске YJ-64.
Результат: Monitor получает сведения только через разрешённый канал.

КОНТРОЛЬ БЛОКА 2:
Проверить оба Monitor-компонента, разрешения, сценарии отказа,
отсутствие автоматической публикации и отсутствие личного содержимого.
Затем Guard Validation и implementation record.

============================================================
БЛОК 3. CI/CD И GUARD-ТРИГГЕРЫ
============================================================

ЦЕЛЬ:
Гарантировать, что каждое значимое изменение запускает необходимые проверки.

ЗАВИСИМОСТЬ: блоки 1–2; критические правила приватности должны быть известны.

ПЕРЕНОС 3.1 — ПОЛНОТА PATHS
В .github/workflows/android-apk.yml проверить и при необходимости
добавить paths для всех влияющих на сборку компонентов:
- llm_api.py, llm_settings.py, chat_workspace.py,
  message_distributor.py;
- services/** и тесты;
- android_src/**, monitor-app/**;
- Java/XML/Gradle/properties;
- buildozer.spec, p4a/** и build hooks;
- Guard и manifest.

ПЕРЕНОС 3.2 — СОБЫТИЯ И ВЕТКИ
- Проверить push, pull_request и workflow_dispatch.
- Проверить список веток-триггеров и целевые ветки.
- Не запускать сборку на нерелевантные изменения, но не пропускать
  ни один критический исходник.

ПЕРЕНОС 3.3 — ПОРЯДОК И ПРОВЕРКА ТРИГГЕРОВ
- Сохранить порядок Guard Validation -> Python compile -> unit tests
  -> Base APK -> Monitor APK -> проверка артефактов и SHA-256.
- Проверить реальным изменением/тестовым запуском, что изменение
  каждого критического файла действительно запускает workflow.
Результат блока 3: полный и предсказуемый CI/CD контур.

КОНТРОЛЬ БЛОКА 3:
Проверить workflow syntax, paths и фактический запуск на тестовом изменении.
Затем Guard Validation и implementation record.

============================================================
БЛОК 4. СЕРВЕРНЫЙ MVP И КОНТРАКТ API
============================================================

ЦЕЛЬ:
Создать переносимый серверный фундамент, не ломая существующий
локальный режим YJ-64.

ЗАВИСИМОСТЬ: блок 3.

ПЕРЕНОС 4.1 — КОНТРАКТ И СХЕМА ДАННЫХ
До создания серверных модулей согласовать:
- пользователей, чаты, участников, сообщения и права доступа;
- идентификаторы сообщений и идемпотентность;
- версии API, ошибки, подтверждения сохранения и пагинацию;
- правила хранения и границы личного контекста.
Результат: утверждённый серверный контракт.

ПЕРЕНОС 4.2 — МИНИМАЛЬНЫЙ СЕРВЕР
Предполагаемая структура:
- server/app/main.py
- server/app/auth.py
- server/app/database.py
- server/app/models.py
- server/app/routes/messages.py
- server/app/routes/chats.py
- server/app/routes/files.py
- server/app/websocket.py
- server/app/storage.py

Начать с FastAPI, PostgreSQL и локального файлового хранилища.
Redis на первом этапе не добавлять.
Результат: сервер запускается и предоставляет базовые endpoint.

ПЕРЕНОС 4.3 — АУТЕНТИФИКАЦИЯ И ДОСТУП
- Реализовать регистрацию/аутентификацию.
- Реализовать пользователей, чаты, участников и сообщения.
- Проверять права доступа на сервере, а не доверять клиентским флагам.
- Добавить два тестовых клиента и проверить разделение данных.
Результат блока 4: серверный MVP обслуживает два клиента.
Ноутбук может быть временным хостом; клиентский протокол не должен
зависеть от конкретного места размещения сервера.

КОНТРОЛЬ БЛОКА 4:
API tests, auth/access tests, persistence tests и Guard Validation.

============================================================
БЛОК 5. КЛИЕНТСКОЕ ХРАНЕНИЕ, СИНХРОНИЗАЦИЯ И ФАЙЛЫ
============================================================

ЦЕЛЬ:
Перевести телефоны на устойчивую работу с сервером без потери
локальных сообщений и вложений.

ЗАВИСИМОСТЬ: блок 4.

ПЕРЕНОС 5.1 — SQLITE И МИГРАЦИЯ
- Сохранить текущий JSON workspace как источник миграции.
- Создать резервную копию и проверить миграцию до отключения JSON.
- Ввести клиентское SQLite-хранилище чатов и сообщений,
  outbox, sync_state и metadata вложений.
Результат: локальные данные хранятся устойчиво и доступны для миграции.

ПЕРЕНОС 5.2 — OUTBOX И ПОДТВЕРЖДЕНИЯ
- Сохранять сообщение локально до отправки.
- Использовать client_message_id и серверную идемпотентность.
- Считать отправку подтверждённой только после записи на сервере.
- Повторная отправка не должна создавать дубликат.
Результат: сообщения не теряются при кратковременном отключении сети.

ПЕРЕНОС 5.3 — ВОССТАНОВЛЕНИЕ СИНХРОНИЗАЦИИ
- Реализовать REST-запрос пропущенных сообщений.
- Восстанавливать историю после отключения/переподключения.
- Проверить два телефона, потерю сети, повторную отправку
  и конфликт данных.
Результат: согласованная история на двух устройствах.

ПЕРЕНОС 5.4 — ПЕРЕДАЧА БИНАРНЫХ ФАЙЛОВ
- Заменить регистрацию только имени файла реальной загрузкой.
- Реализовать серверное хранение, metadata и проверку прав.
- Реализовать скачивание на втором устройстве и SHA-256 после передачи.
- Для больших файлов добавить chunk upload и возобновление после обрыва.
- На Android перейти от прямых путей FileChooserListView
  к системному Storage Access Framework.
- Проверить размер, тип, отмену, повтор и частичный сбой.
Результат блока 5: сообщения и файлы синхронизируются между устройствами.

КОНТРОЛЬ БЛОКА 5:
Миграция без потери данных, offline/online tests, duplicate prevention,
file transfer tests и Guard Validation.

============================================================
БЛОК 6. AGENT GATEWAY И ПЕРЕНОС ВЫЗОВОВ МОДЕЛЕЙ НА СЕРВЕР
============================================================

ЦЕЛЬ:
Сохранить текущую маршрутизацию агентов, но отделить её от локального
исполнения и перенести секреты с телефона.

ЗАВИСИМОСТЬ: блоки 4–5. Файловый перенос не блокирует подготовку Gateway,
если контракт сообщений и прав уже утверждён.

ПЕРЕНОС 6.1 — ИНТЕРФЕЙС GATEWAY
- Сохранить MessageDistributor как компонент выбора адресата,
  агента, режима и разрешённого контекста.
- Ввести единый AgentGateway.
- Предусмотреть LocalGateway для тестов и RemoteGateway
  для серверного исполнения.
- Не ломать существующий локальный режим.
Результат: единый интерфейс для локального и удалённого исполнения.

ПЕРЕНОС 6.2 — СЕРВЕРНОЕ ИСПОЛНЕНИЕ
- Реализовать server/app/llm_gateway.py.
- Перевести вызовы провайдеров с локального llm_api.generate_response()
  на согласованный серверный интерфейс.
- Проверить тайм-ауты, ошибки провайдера и лимиты.
Результат: модели вызываются через серверный Gateway.

ПЕРЕНОС 6.3 — ПЕРЕНОС И ЗАЩИТА API-КЛЮЧЕЙ
- Перенести ключи OpenAI/Gemini/Mistral и других провайдеров
  в защищённое серверное хранилище.
- На телефоне оставить идентификаторы маршрутов и настройки интерфейса.
- Сначала проверить работу серверных ключей и маршрутов;
  только после этого удалять локальные секреты.
- Проверить, что чужой личный контекст не уходит другому агенту/провайдеру.
Результат блока 6: телефон не хранит ключи провайдеров,
а запросы выполняются с соблюдением правил доступа.

КОНТРОЛЬ БЛОКА 6:
Local/Remote parity tests, routing tests, secret-handling tests,
privacy tests и Guard Validation.

============================================================
БЛОК 7. ОЧЕРЕДЬ АГЕНТОВ, ФОНОВАЯ ДОСТАВКА И ЗАВЕРШАЮЩАЯ ИНТЕГРАЦИЯ
============================================================

ЦЕЛЬ:
Обеспечить выполнение длительных задач, доставку результатов и
переносимость всей системы.

ЗАВИСИМОСТЬ: блоки 4 и 6; синхронизация блока 5 должна иметь базовую
устойчивую реализацию.

ПЕРЕНОС 7.1 — СЕРВЕРНАЯ ОЧЕРЕДЬ ЗАДАЧ
- Реализовать task_queue в PostgreSQL.
- Поля: task_id, owner_id, chat_id, status, priority, timestamps,
  retry_count, timeout, cancel и result.
- Добавить ограниченный параллелизм, повторные попытки и восстановление
  незавершённых задач после перезапуска сервера.
Результат: серверная очередь переживает перезапуск и сбои.

ПЕРЕНОС 7.2 — ДОСТАВКА РЕЗУЛЬТАТОВ
- При открытом приложении использовать WebSocket и переподключение.
- При возвращении в приложение выполнять REST-синхронизацию
  пропущенных событий.
- FCM добавлять только после надёжной foreground-синхронизации.
- Не делать постоянный WebSocket обязательным фоновым механизмом Android.
Результат: результаты задач доставляются надёжно и без зависимости
от постоянной фоновой работы телефона.

ПЕРЕНОС 7.3 — ПОЭТАПНОЕ РАЗДЕЛЕНИЕ main.py
- Выносить UI чатов, вложения, удалённое соединение, синхронизацию,
  архивы, диагностику и agent client в отдельные модули.
- Не переписывать main.py целиком.
- Удалять старые участки только после проверки функциональной эквивалентности.
Результат: уменьшение связанности без потери существующих функций.

ПЕРЕНОС 7.4 — END-TO-END ИНТЕГРАЦИЯ
- Проверить два устройства и разные сети.
- Проверить reconnect, историю, файлы, приватные контексты,
  несколько агентов и сбои сервера.
- Проверить перенос того же серверного приложения с ноутбука
  в дата-центр без изменения клиентского протокола.
- Обновить защищённые фрагменты и Git blob SHA по фактическому коду.
Результат блока 7: подтверждённая интеграция всей системы.

КОНТРОЛЬ БЛОКА 7:
End-to-end tests, privacy/access tests, restart/reconnect tests,
Guard Validation PASS; затем CI и APK.

============================================================
ПРАВИЛО ЗАВЕРШЕНИЯ КАЖДОГО БЛОКА
============================================================

Блок считается завершённым только когда:
1. Все согласованные переносы блока выполнены.
2. Для каждого переноса проверена точность изменения.
3. Выполнены относящиеся к блоку тесты.
4. Guard Validation завершился PASS.
5. Обновлены защищённые фрагменты и контрольные Git blob SHA.
6. Добавлен краткий implementation record с перечнем файлов,
   фактическими изменениями, проверками и известными ограничениями.
7. Операционный стол очищен от завершённых патчей.

После этого выбирается следующий блок. APK запускается только тогда,
когда это необходимо для проверки результата и Guard уже дал PASS.

ТЕКУЩАЯ ПОЗИЦИЯ:
БЛОК 1 — ожидает пошагового аудита и согласования переноса 1.1.
Операционный стол остаётся CLEAN; активных патчей нет.

============================================================
