"""crm.py add-note / list-notes 追加后重新查询流程的回归测试。

固定两个入口在“为联系人追加备注、随后重新查询同一数据库”这条流程上的
公开命令行行为：

- 已有联系人尚无备注时，list-notes 成功返回空数组；
- 交替为星河科技林宁与远帆咨询周岚追加备注，正文可包含中文、内部空格、
  制表符与换行；add-note 成功时退出码为 0、标准错误为空，标准输出整体
  是含 id/contact_id/text 的单个 JSON 对象，备注编号为正整数，
  contact_id 对应目标联系人，正文仅去除首尾空白而保留内部字符；
- 通过新的命令调用 list-notes 查询同一数据库，结果按备注编号升序，
  与追加输出逐条一致，且不会混入另一联系人的备注；
- 重复追加相同正文产生两条编号不同的独立记录；
- 联系人编号带首尾空白与前导零时仍指向同一人；备注操作不改变两人的
  资料与联系人数量；
- 编号为 0、非数字或超过 9223372036854775807 时，两个入口均以退出码 2
  结束、标准输出为空、标准错误恰为单行
  ``id: must be a positive integer``；
- add-note 正文为空或纯空白时报 ``text: must not be empty``，编号与正文
  同时无效时先报编号错误；
- 合法编号 99 不存在时两入口均报 ``id: contact not found``；参数合法但
  数据库父目录不存在时均报 ``db: parent directory does not exist``；
  这些失败同样使用退出码 2 与空标准输出；
- 失败后已有联系人与备注保持不变；输入校验失败不创建新数据库，
  合法参数在父目录存在的新数据库上遇到联系人不存在时保留已初始化的空库。

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
所有样例数据都放在独立的临时目录中，测试结束后自动清理。
在项目根目录运行：python -m unittest discover -s tests
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM_SCRIPT = PROJECT_ROOT / "crm.py"

ID_ERROR_LINE = "id: must be a positive integer"
TEXT_ERROR_LINE = "text: must not be empty"
NOT_FOUND_LINE = "id: contact not found"
DB_ERROR_LINE = "db: parent directory does not exist"

MAX_CONTACT_ID = 9223372036854775807

# 编号校验失败样例：0、非数字、超过 64 位有符号整数上限，以及其他非正整数形态
INVALID_IDS = ["0", "abc", str(MAX_CONTACT_ID + 1), "   ", "1.5", "-3"]

# 纯空白正文样例（空串、空格、制表符、换行混合）
BLANK_TEXTS = ["", "   ", "\t", "\n \t"]

# 林宁的备注正文：首尾带空白，内部保留中文、空格、制表符与换行
LIN_NOTE_TEXTS = [
    "  林宁备注 首条：内部 空格\n第二行 仍有空格  ",
    "\t\n林宁第二条\t含制表符 与换行\n  ",
    " 林宁第三条：纯中文编号三 ",
]

# 周岚的备注正文同样混入内部空白与换行
ZHOU_NOTE_TEXTS = [
    "周岚第一条",
    " 周岚 第二条\n带换行 ",
    "\tzhou third note\t",
]

# 重复追加的正文：两次相同输入应得到两条独立记录
DUPLICATE_TEXT = "  重复正文 同样内容  "


class ContactNotesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self.db_path = self.tmpdir / "contacts.sqlite3"

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def add_contact(self, db_path, name, email, company):
        return self.run_crm(
            db_path, "add", "--name", name, "--email", email, "--company", company
        )

    def get_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "get", "--id", str(contact_id))

    def list_company(self, db_path, company):
        return self.run_crm(db_path, "list", "--company", company)

    def add_note(self, db_path, contact_id, text):
        return self.run_crm(
            db_path, "add-note", "--id", str(contact_id), "--text", text
        )

    def list_notes(self, db_path, contact_id):
        return self.run_crm(db_path, "list-notes", "--id", str(contact_id))

    # ---- 通用断言 ----

    def assert_command_rejected(self, result, expected_stderr_line):
        """断言命令失败：退出码 2、无标准输出、标准错误恰为单行且无堆栈。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )
        self.assertNotIn(b"Traceback", result.stderr)

    def assert_add_note_success(self, result, contact_id, expected_text):
        """断言 add-note 成功并返回解析后的备注字典。

        退出码 0、标准错误为空，标准输出整体是单个 JSON 对象，
        只含 id/contact_id/text 三个字段；id 为正整数，contact_id 与
        目标联系人一致，正文恰为期盼值（仅去除首尾空白）。
        """
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(set(record.keys()), {"id", "contact_id", "text"})
        self.assertIsInstance(record["id"], int)
        self.assertGreater(record["id"], 0)
        self.assertEqual(record["contact_id"], contact_id)
        self.assertEqual(record["text"], expected_text)
        return record

    def assert_list_notes_success(
        self, db_path, contact_id, expected_records, expected_contact_id=None
    ):
        """断言 list-notes 返回的备注（含顺序）与期望完全一致。

        contact_id 是命令行上传入的原始编号（可带首尾空白与前导零）；
        expected_contact_id 指定归属核对所用的整数编号，省略时直接取
        contact_id（适用于传入纯整数的调用）。
        """
        if expected_contact_id is None:
            expected_contact_id = contact_id
        result = self.list_notes(db_path, contact_id)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(records, expected_records)
        for record in records:
            self.assertEqual(set(record.keys()), {"id", "contact_id", "text"})
            self.assertEqual(record["contact_id"], expected_contact_id)
        return records

    def seed_two_contacts(self):
        """在全新数据库依次新增林宁（星河科技）与周岚（远帆咨询）。"""
        def add(name, email, company):
            result = self.add_contact(self.db_path, name, email, company)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stderr, b"")
            record = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            return record

        lin = add("林宁", "lin@example.test", "星河科技")
        zhou = add("周岚", "zhou@example.test", "远帆咨询")
        self.assertLess(lin["id"], zhou["id"])
        return lin, zhou

    def assert_contacts_unchanged(self, lin, zhou):
        """备注操作后两人资料、两家公司联系人数与顺序均保持不变。"""
        lin_now = json.loads(self.get_contact(self.db_path, lin["id"]).stdout)
        zhou_now = json.loads(self.get_contact(self.db_path, zhou["id"]).stdout)
        self.assertEqual(lin_now, lin)
        self.assertEqual(zhou_now, zhou)
        self.assert_list_records("星河科技", [lin])
        self.assert_list_records("远帆咨询", [zhou])

    def assert_list_records(self, company, expected_records):
        result = self.list_company(self.db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), expected_records)

    # ---- 追加后重新查询主流程 ----

    def test_list_notes_returns_empty_array_before_any_note(self):
        lin, zhou = self.seed_two_contacts()

        for contact in (lin, zhou):
            with self.subTest(contact=contact["name"]):
                self.assert_list_notes_success(self.db_path, contact["id"], [])

    def test_alternating_add_notes_then_requery_matches_and_stays_partitioned(self):
        lin, zhou = self.seed_two_contacts()

        lin_records = []
        zhou_records = []

        # 交替为两人追加备注；林宁的正文含中文、内部空格、制表符、换行
        # 及首尾空白
        for index in range(3):
            lin_text = LIN_NOTE_TEXTS[index]
            lin_record = self.assert_add_note_success(
                self.add_note(self.db_path, lin["id"], lin_text),
                lin["id"],
                lin_text.strip(),
            )
            lin_records.append(lin_record)

            zhou_text = ZHOU_NOTE_TEXTS[index]
            zhou_record = self.assert_add_note_success(
                self.add_note(self.db_path, zhou["id"], zhou_text),
                zhou["id"],
                zhou_text.strip(),
            )
            zhou_records.append(zhou_record)

        # 交替追加时备注编号全局递增
        all_ids = [r["id"] for r in lin_records] + [r["id"] for r in zhou_records]
        self.assertEqual(len(set(all_ids)), len(all_ids))

        # 通过新的命令调用重新查询同一数据库：按备注编号升序，
        # 与追加输出逐条一致，且互不混入对方备注
        lin_notes = self.assert_list_notes_success(
            self.db_path, lin["id"], lin_records
        )
        self.assertEqual([r["id"] for r in lin_notes], sorted(r["id"] for r in lin_notes))
        self.assertEqual(
            [r["text"] for r in lin_notes],
            [text.strip() for text in LIN_NOTE_TEXTS],
        )
        self.assertTrue(
            all(r["id"] not in {n["id"] for n in zhou_records} for r in lin_notes)
        )

        zhou_notes = self.assert_list_notes_success(
            self.db_path, zhou["id"], zhou_records
        )
        self.assertEqual(
            [r["id"] for r in zhou_notes], sorted(r["id"] for r in zhou_notes)
        )
        self.assertTrue(
            all(r["id"] not in {n["id"] for n in lin_records} for r in zhou_notes)
        )

        # 正文内部空白原样保留：抽查首条林宁备注的换行与内部空格
        self.assertIn("\n", lin_notes[0]["text"])
        self.assertIn("内部 空格", lin_notes[0]["text"])
        self.assertIn("\t", lin_notes[1]["text"])
        # 首尾空白确实被去除
        self.assertEqual(lin_notes[0]["text"], lin_notes[0]["text"].strip())

        # 备注操作不改变联系人资料与数量
        self.assert_contacts_unchanged(lin, zhou)

    def test_repeated_same_text_creates_two_independent_notes(self):
        lin, _zhou = self.seed_two_contacts()

        first = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], DUPLICATE_TEXT),
            lin["id"],
            DUPLICATE_TEXT.strip(),
        )
        second = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], DUPLICATE_TEXT),
            lin["id"],
            DUPLICATE_TEXT.strip(),
        )

        # 两条独立记录：编号不同且严格递增，正文与归属完全相同
        self.assertNotEqual(first["id"], second["id"])
        self.assertLess(first["id"], second["id"])
        self.assertEqual(first["contact_id"], second["contact_id"])
        self.assertEqual(first["text"], second["text"])

        notes = self.assert_list_notes_success(
            self.db_path, lin["id"], [first, second]
        )
        self.assertEqual([r["id"] for r in notes], [first["id"], second["id"]])

    def test_padded_and_leading_zero_id_still_targets_same_contact(self):
        lin, zhou = self.seed_two_contacts()

        padded_lin_id = f"  \t000{lin['id']}  "
        record = self.assert_add_note_success(
            self.add_note(self.db_path, padded_lin_id, " 编号带空白与前导零 "),
            lin["id"],
            "编号带空白与前导零",
        )

        # list-notes 同样接受带空白与前导零的编号，并只返回林宁的备注
        notes = self.assert_list_notes_success(
            self.db_path, padded_lin_id, [record], expected_contact_id=lin["id"]
        )
        self.assertEqual(notes[0]["contact_id"], lin["id"])

        # 周岚的备注列表仍为空，未被串号写入
        self.assert_list_notes_success(self.db_path, f" {zhou['id']}\t", [])

        self.assert_contacts_unchanged(lin, zhou)

    # ---- 编号校验：两个入口行为一致 ----

    def test_invalid_ids_are_rejected_by_both_commands(self):
        lin, zhou = self.seed_two_contacts()
        # 先准备一条备注，用于核对失败后备注保持不变
        existing = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], " 已存在备注 "),
            lin["id"],
            "已存在备注",
        )

        for raw_id in INVALID_IDS:
            with self.subTest(command="add-note", raw_id=raw_id):
                self.assert_command_rejected(
                    self.add_note(self.db_path, raw_id, "任意正文"),
                    ID_ERROR_LINE,
                )
            with self.subTest(command="list-notes", raw_id=raw_id):
                self.assert_command_rejected(
                    self.list_notes(self.db_path, raw_id), ID_ERROR_LINE
                )

            # 失败后联系人与备注保持不变
            self.assert_list_notes_success(self.db_path, lin["id"], [existing])
            self.assert_list_notes_success(self.db_path, zhou["id"], [])
        self.assert_contacts_unchanged(lin, zhou)

    def test_invalid_ids_do_not_create_missing_database(self):
        for index, raw_id in enumerate(INVALID_IDS):
            fresh_db = self.tmpdir / f"notes-invalid-id-{index}.sqlite3"
            with self.subTest(command="add-note", raw_id=raw_id):
                self.assertFalse(fresh_db.exists())
                self.assert_command_rejected(
                    self.add_note(fresh_db, raw_id, "任意正文"), ID_ERROR_LINE
                )
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

            fresh_db.unlink(missing_ok=True)
            with self.subTest(command="list-notes", raw_id=raw_id):
                self.assertFalse(fresh_db.exists())
                self.assert_command_rejected(
                    self.list_notes(fresh_db, raw_id), ID_ERROR_LINE
                )
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    # ---- add-note 正文校验 ----

    def test_blank_text_is_rejected_after_id_passes(self):
        lin, zhou = self.seed_two_contacts()

        for text in BLANK_TEXTS:
            with self.subTest(text=repr(text)):
                self.assert_command_rejected(
                    self.add_note(self.db_path, lin["id"], text),
                    TEXT_ERROR_LINE,
                )
                # 未写入任何备注
                self.assert_list_notes_success(self.db_path, lin["id"], [])
                self.assert_list_notes_success(self.db_path, zhou["id"], [])
        self.assert_contacts_unchanged(lin, zhou)

    def test_blank_text_does_not_create_missing_database(self):
        for index, text in enumerate(BLANK_TEXTS):
            fresh_db = self.tmpdir / f"notes-blank-text-{index}.sqlite3"
            with self.subTest(text=repr(text)):
                self.assertFalse(fresh_db.exists())
                self.assert_command_rejected(
                    self.add_note(fresh_db, "1", text), TEXT_ERROR_LINE
                )
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_invalid_id_and_blank_text_reports_id_error_first(self):
        lin, _zhou = self.seed_two_contacts()

        for raw_id in INVALID_IDS:
            for text in BLANK_TEXTS:
                with self.subTest(raw_id=raw_id, text=repr(text)):
                    self.assert_command_rejected(
                        self.add_note(self.db_path, raw_id, text),
                        ID_ERROR_LINE,
                    )

        # 全部失败后仍无任何备注
        self.assert_list_notes_success(self.db_path, lin["id"], [])

    # ---- 联系人不存在 ----

    def test_unknown_id_99_reports_not_found_in_both_commands(self):
        lin, zhou = self.seed_two_contacts()
        existing = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], " 已有备注 "),
            lin["id"],
            "已有备注",
        )

        self.assert_command_rejected(
            self.add_note(self.db_path, "99", "新备注"), NOT_FOUND_LINE
        )
        self.assert_command_rejected(
            self.list_notes(self.db_path, "99"), NOT_FOUND_LINE
        )

        # 失败后联系人与备注保持不变
        self.assert_list_notes_success(self.db_path, lin["id"], [existing])
        self.assert_list_notes_success(self.db_path, zhou["id"], [])
        self.assert_contacts_unchanged(lin, zhou)

    def test_unknown_id_on_new_database_initializes_and_keeps_empty_database(self):
        for command in ("add-note", "list-notes"):
            fresh_db = self.tmpdir / f"notes-unknown-{command}.sqlite3"
            with self.subTest(command=command):
                self.assertFalse(fresh_db.exists())
                if command == "add-note":
                    result = self.add_note(fresh_db, "99", "新备注")
                else:
                    result = self.list_notes(fresh_db, "99")
                self.assert_command_rejected(result, NOT_FOUND_LINE)
                # 合法参数 + 父目录存在：空数据库已初始化并保留
                self.assertTrue(fresh_db.exists())

                # 随后跨公司列表返回空数组，库可正常复用
                result_list = self.list_company(fresh_db, "星河科技")
                self.assertEqual(result_list.returncode, 0)
                self.assertEqual(result_list.stderr, b"")
                self.assertEqual(
                    json.loads(result_list.stdout.decode("utf-8")), []
                )

    # ---- 数据库父目录不存在 ----

    def test_missing_parent_directory_is_rejected_by_both_commands(self):
        lin, zhou = self.seed_two_contacts()
        existing = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], " 已有备注 "),
            lin["id"],
            "已有备注",
        )

        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        # 参数合法、仅父目录缺失：两个入口都报 db 错误
        self.assert_command_rejected(
            self.add_note(fresh_db, "1", "正文"), DB_ERROR_LINE
        )
        self.assert_command_rejected(
            self.list_notes(fresh_db, "1"), DB_ERROR_LINE
        )
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

        # 失败后已有联系人与备注保持不变
        self.assert_list_notes_success(self.db_path, lin["id"], [existing])
        self.assert_list_notes_success(self.db_path, zhou["id"], [])
        self.assert_contacts_unchanged(lin, zhou)


if __name__ == "__main__":
    unittest.main()
