"""crm.py update-name 改名为他人同名姓名时保留联系人备注的回归测试。

围绕“更新姓名不得影响编号与备注归属”这一既有行为，从公开命令行输入
到返回结果展开端到端核对：

- 用 add 新建星河科技的林宁、许禾与远帆咨询的周岚，以各次 add 返回的
  编号为准（不预设自增编号），再用 add-note 依次给林宁追加“首次联系”、
  给周岚追加“确认资料”、再次给林宁追加“首次联系”，保留 add-note 返回的
  完整备注 JSON（id/contact_id/text）；
- update-name 将林宁的姓名改成首尾带空格的“  周岚  ”时，退出码 0、
  标准错误为空，标准输出是更新后的完整联系人 JSON，仅 name 变为
  “周岚”，编号、邮箱、公司保持原值；
- 随后以独立命令调用 get 与 list-notes：林宁的资料与更新结果一致，
  其两条备注按备注编号升序返回，与两次 add-note 的输出逐字段一致
  （两条“首次联系”编号不同，可发现重复记录被合并的回归）；周岚的资料
  与备注保持原样；许禾资料不变且备注为空数组（可发现备注串到其他
  联系人的回归）；
- list --name 周岚 跨公司返回两个不同编号的联系人并按编号升序；按旧
  姓名“林宁”查询返回空数组；对林宁再次提交相同姓名同样成功，联系人
  与备注的数量和内容均不改变（可发现备注丢失或重复写入）；
- 用同样已带备注的数据验证更新被拒绝时的保留结果：编号 0 配合合法
  姓名报 id: must be a positive integer，合法编号配合空串或纯空白
  姓名报 name: must not be empty，编号 99 配合合法姓名报
  id: contact not found，编号与姓名同时无效时只报告编号错误；上述
  失败均退出 2、标准输出为空、标准错误仅含对应一行及结尾换行，
  失败后三个联系人的资料与全部备注与失败前完全一致。

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

LIN_NAME = "林宁"
LIN_EMAIL = "lin@example.test"

XU_NAME = "许禾"
XU_EMAIL = "xu@example.test"

ZHOU_NAME = "周岚"
ZHOU_EMAIL = "zhou@example.test"

XINGHE_COMPANY = "星河科技"
YUANFAN_COMPANY = "远帆咨询"

ZHOU_NAME_PADDED = "  周岚  "

LIN_NOTE_TEXT = "首次联系"
ZHOU_NOTE_TEXT = "确认资料"

ID_ERROR_LINE = "id: must be a positive integer"
NAME_ERROR_LINE = "name: must not be empty"
NOT_FOUND_LINE = "id: contact not found"

UNKNOWN_CONTACT_ID = "99"


class UpdateNamePreservesNotesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self.db_path = self.tmpdir / "contacts.sqlite3"

    # ---- 命令执行与解析辅助 ----

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def add_contact(self, name, email, company):
        """add 成功时返回解析后的联系人字典。"""
        result = self.run_crm(
            self.db_path,
            "add",
            "--name",
            name,
            "--email",
            email,
            "--company",
            company,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertEqual(record["name"], name)
        self.assertEqual(record["email"], email)
        self.assertEqual(record["company"], company)
        return record

    def add_note(self, contact_id, text):
        """add-note 成功时返回解析后的完整备注字典。"""
        result = self.run_crm(
            self.db_path, "add-note", "--id", str(contact_id), "--text", text
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "contact_id", "text"})
        return record

    def update_name(self, contact_id, name):
        return self.run_crm(
            self.db_path,
            "update-name",
            "--id",
            str(contact_id),
            "--name",
            name,
        )

    def get_contact(self, contact_id):
        """get 成功时返回解析后的联系人字典。"""
        result = self.run_crm(self.db_path, "get", "--id", str(contact_id))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout.decode("utf-8"))

    def list_notes(self, contact_id):
        """list-notes 成功时返回解析后的备注数组。"""
        result = self.run_crm(self.db_path, "list-notes", "--id", str(contact_id))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout.decode("utf-8"))

    def list_by_name(self, name):
        """list --name（省略公司，跨全部公司）成功时返回解析后的联系人数组。"""
        result = self.run_crm(self.db_path, "list", "--name", name)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout.decode("utf-8"))

    def assert_rejected(self, result, expected_stderr_line):
        """断言命令被拒绝：退出码 2、无标准输出、标准错误恰为单行加换行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )
        self.assertNotIn(b"Traceback", result.stderr)

    # ---- 固定合成资料 ----

    def seed_noted_contacts(self):
        """新建三名联系人并追加三条备注，返回全部 add/add-note 输出。

        联系人依次为林宁、许禾（星河科技）与周岚（远帆咨询）；备注依次为
        林宁“首次联系”、周岚“确认资料”、林宁“首次联系”。编号一律取各次
        命令的实际返回值，不依赖自增起始值。
        """
        lin = self.add_contact(LIN_NAME, LIN_EMAIL, XINGHE_COMPANY)
        xu = self.add_contact(XU_NAME, XU_EMAIL, XINGHE_COMPANY)
        zhou = self.add_contact(ZHOU_NAME, ZHOU_EMAIL, YUANFAN_COMPANY)
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])

        note_lin_first = self.add_note(lin["id"], LIN_NOTE_TEXT)
        note_zhou = self.add_note(zhou["id"], ZHOU_NOTE_TEXT)
        note_lin_second = self.add_note(lin["id"], LIN_NOTE_TEXT)

        self.assertEqual(
            note_lin_first,
            {"id": note_lin_first["id"], "contact_id": lin["id"], "text": LIN_NOTE_TEXT},
        )
        self.assertEqual(
            note_zhou,
            {"id": note_zhou["id"], "contact_id": zhou["id"], "text": ZHOU_NOTE_TEXT},
        )
        self.assertEqual(
            note_lin_second,
            {
                "id": note_lin_second["id"],
                "contact_id": lin["id"],
                "text": LIN_NOTE_TEXT,
            },
        )
        # 两条同文备注编号不同且全局按追加顺序递增（防合并的前提）
        self.assertNotEqual(note_lin_first["id"], note_lin_second["id"])
        self.assertLess(note_lin_first["id"], note_zhou["id"])
        self.assertLess(note_zhou["id"], note_lin_second["id"])

        return {
            "lin": lin,
            "xu": xu,
            "zhou": zhou,
            "note_lin_first": note_lin_first,
            "note_lin_second": note_lin_second,
            "note_zhou": note_zhou,
        }

    # ---- 全量状态快照（联系人资料 + 各联系人备注） ----

    def snapshot_state(self, contacts):
        """通过公开命令记录三个联系人当前的资料与备注。"""
        lin, xu, zhou = contacts
        return {
            "contacts": {
                lin["id"]: self.get_contact(lin["id"]),
                xu["id"]: self.get_contact(xu["id"]),
                zhou["id"]: self.get_contact(zhou["id"]),
            },
            "notes": {
                lin["id"]: self.list_notes(lin["id"]),
                xu["id"]: self.list_notes(xu["id"]),
                zhou["id"]: self.list_notes(zhou["id"]),
            },
        }

    def assert_state_equals(self, expected):
        """重新查询并断言资料与备注与快照逐字段一致。"""
        for contact_id, contact_record in expected["contacts"].items():
            self.assertEqual(self.get_contact(contact_id), contact_record)
        for contact_id, note_records in expected["notes"].items():
            self.assertEqual(self.list_notes(contact_id), note_records)

    # ---- 更新成功：姓名改为他人同名，编号与备注原样保留 ----

    def test_update_name_to_existing_name_preserves_all_notes(self):
        data = self.seed_noted_contacts()
        lin = data["lin"]
        xu = data["xu"]
        zhou = data["zhou"]
        note_lin_first = data["note_lin_first"]
        note_lin_second = data["note_lin_second"]
        note_zhou = data["note_zhou"]

        # 将林宁的姓名改成首尾带空白的“  周岚  ”（与远帆咨询的周岚同名）
        result = self.update_name(lin["id"], ZHOU_NAME_PADDED)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

        updated_lin = {
            "id": lin["id"],
            "name": ZHOU_NAME,
            "email": LIN_EMAIL,
            "company": XINGHE_COMPANY,
        }
        # 标准输出整体就是一行完整联系人 JSON：仅 name 改变，
        # 编号、邮箱、公司保持原值，姓名首尾空白被清除
        self.assertEqual(
            result.stdout.decode("utf-8"),
            json.dumps(updated_lin, ensure_ascii=False) + "\n",
        )

        # 独立调用 get：林宁的资料与更新结果一致，许禾、周岚保持原值
        self.assertEqual(self.get_contact(lin["id"]), updated_lin)
        self.assertEqual(self.get_contact(xu["id"]), xu)
        self.assertEqual(self.get_contact(zhou["id"]), zhou)

        # 独立调用 list-notes：林宁的两条备注按备注编号升序返回，
        # 与 add-note 返回的 id/contact_id/text 完全一致；
        # 周岚的备注保持原样，许禾仍为空数组
        lin_notes = self.list_notes(lin["id"])
        self.assertEqual(lin_notes, [note_lin_first, note_lin_second])
        self.assertEqual(
            [note["id"] for note in lin_notes],
            sorted(note["id"] for note in lin_notes),
        )
        self.assertTrue(
            all(note["contact_id"] == lin["id"] for note in lin_notes)
        )
        self.assertEqual(self.list_notes(zhou["id"]), [note_zhou])
        self.assertEqual(self.list_notes(xu["id"]), [])

        # list --name 周岚 跨公司返回两个不同编号的联系人，按编号升序；
        # 按旧姓名“林宁”查询返回空数组
        zhou_records = self.list_by_name(ZHOU_NAME)
        self.assertEqual(zhou_records, [updated_lin, zhou])
        self.assertEqual(
            [record["id"] for record in zhou_records],
            sorted(record["id"] for record in zhou_records),
        )
        self.assertEqual(
            len({record["id"] for record in zhou_records}), len(zhou_records)
        )
        self.assertEqual(self.list_by_name(LIN_NAME), [])

        # 对林宁再次提交相同姓名仍应成功，输出与上次完全一致
        repeat = self.update_name(lin["id"], ZHOU_NAME)
        self.assertEqual(repeat.returncode, 0, repeat.stderr.decode("utf-8"))
        self.assertEqual(repeat.stderr, b"")
        self.assertEqual(
            repeat.stdout.decode("utf-8"),
            json.dumps(updated_lin, ensure_ascii=False) + "\n",
        )

        # 联系人与备注的数量及内容均不改变：不丢备注、不重复写入、不串号
        self.assertEqual(self.list_by_name(ZHOU_NAME), [updated_lin, zhou])
        self.assertEqual(self.list_by_name(LIN_NAME), [])
        self.assertEqual(
            self.list_notes(lin["id"]), [note_lin_first, note_lin_second]
        )
        self.assertEqual(self.list_notes(zhou["id"]), [note_zhou])
        self.assertEqual(self.list_notes(xu["id"]), [])
        self.assertEqual(self.get_contact(lin["id"]), updated_lin)
        self.assertEqual(self.get_contact(xu["id"]), xu)
        self.assertEqual(self.get_contact(zhou["id"]), zhou)

    # ---- 更新被拒绝：三个联系人的资料与全部备注保持失败前状态 ----

    def test_rejected_name_updates_leave_contacts_and_notes_unchanged(self):
        data = self.seed_noted_contacts()
        lin = data["lin"]
        xu = data["xu"]
        zhou = data["zhou"]

        # 样例库只有三名联系人，编号 99 必然不存在
        self.assertLess(max(lin["id"], xu["id"], zhou["id"]), int(UNKNOWN_CONTACT_ID))

        contacts = (lin, xu, zhou)
        state_before = self.snapshot_state(contacts)

        # (编号输入, 姓名输入, 期望的标准错误单行)
        rejected_cases = [
            # 编号为 0 配合合法姓名
            ("0", ZHOU_NAME, ID_ERROR_LINE),
            # 合法联系人编号配合空串或纯空白姓名
            (str(lin["id"]), "", NAME_ERROR_LINE),
            (str(lin["id"]), "   ", NAME_ERROR_LINE),
            (str(lin["id"]), "\t \t", NAME_ERROR_LINE),
            # 编号 99 不存在但姓名合法
            (UNKNOWN_CONTACT_ID, ZHOU_NAME, NOT_FOUND_LINE),
            # 编号与姓名同时无效时只报告编号错误
            ("0", "   ", ID_ERROR_LINE),
        ]

        for raw_id, name, expected_error in rejected_cases:
            with self.subTest(raw_id=raw_id, name=repr(name)):
                result = self.update_name(raw_id, name)
                self.assert_rejected(result, expected_error)

                # 每次失败后立即重新查询：资料与备注逐字段不变
                self.assert_state_equals(state_before)

        # 全部失败后再做一次显式核对：三名联系人资料不变，林宁两条同文
        # 备注均在且编号不变，周岚备注原样，许禾没有备注
        self.assertEqual(self.get_contact(lin["id"]), lin)
        self.assertEqual(self.get_contact(xu["id"]), xu)
        self.assertEqual(self.get_contact(zhou["id"]), zhou)
        self.assertEqual(
            self.list_notes(lin["id"]),
            [data["note_lin_first"], data["note_lin_second"]],
        )
        self.assertEqual(self.list_notes(zhou["id"]), [data["note_zhou"]])
        self.assertEqual(self.list_notes(xu["id"]), [])


if __name__ == "__main__":
    unittest.main()
