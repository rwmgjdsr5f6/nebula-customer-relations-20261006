"""crm.py 首次在仅有 contacts 表的既有数据库上使用备注功能的回归测试。

覆盖“复用旧库时补建缺失的 notes 表且保留原有资料”这一既有行为，
从公开命令行输入到返回结果端到端核对：

- 样例库直接用 sqlite3 按当前 contacts 表结构（含 AUTOINCREMENT 与
  sqlite_sequence 自增编号信息）手工构造，不含 notes 表，且首次备注
  操作前不经过任何其他产品命令访问；预置编号 7 的林宁、编号 11 的许禾
  （星河科技）与编号 15 的周岚（远帆咨询）；
- 查询先发生：首条命令 list-notes --id 7 即完成备注表初始化，输出 []、
  退出码 0、标准错误为空；随后 add-note --id 7 --text " 首次联系 "
  输出单个 JSON 对象，备注编号 1、contact_id 为 7、正文为“首次联系”；
- 追加先发生：另一份相同初始状态的样例直接追加同一条备注，返回与查询
  先发生路径完全相同的结果（备注编号同样从 1 开始）；
- 两份样例都通过新的独立命令调用重新查询：编号 7 的 list-notes 只返回
  这一条备注，编号 11 与 15 仍返回 []；成功调用退出码均为 0、标准错误
  为空，重复查询不会清空备注；
- 初始化边界上的失败结果：未补表的样例上 list-notes --id 0 的标准错误
  仅为 id: must be a positive integer 一行，add-note --id 7
  --text "   " 仅为 text: must not be empty 一行；二者退出码 2、
  标准输出为空，notes 表仍不存在；另一份未补表样例执行
  list-notes --id 99 时先初始化备注表，再以退出码 2、空标准输出和
  id: contact not found 一行结束；
- 每个用例的三个联系人编号、完整字段与数量始终不变，sqlite_sequence
  中的联系人自增编号信息保持原值。

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
所有样例数据都放在独立的临时目录中，测试结束后自动清理。
在项目根目录运行：python -m unittest discover -s tests
"""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM_SCRIPT = PROJECT_ROOT / "crm.py"

LIN = {"id": 7, "name": "林宁", "email": "lin@example.test", "company": "星河科技"}
XU = {"id": 11, "name": "许禾", "email": "xu@example.test", "company": "星河科技"}
ZHOU = {"id": 15, "name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"}

SEED_CONTACTS = [LIN, XU, ZHOU]
SEED_MAX_ID = max(contact["id"] for contact in SEED_CONTACTS)

LIN_ID = LIN["id"]
XU_ID = XU["id"]
ZHOU_ID = ZHOU["id"]
UNKNOWN_ID = 99

FIRST_NOTE_RAW = " 首次联系 "
FIRST_NOTE_TEXT = "首次联系"

ID_ERROR_LINE = "id: must be a positive integer"
TEXT_ERROR_LINE = "text: must not be empty"
NOT_FOUND_LINE = "id: contact not found"

# 与 crm.py 当前 contacts 表结构逐字一致：既有库只含此表（AUTOINCREMENT
# 会随之产生 sqlite_sequence 自增编号信息），不含 notes 表。
LEGACY_CONTACTS_DDL = """
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    company TEXT NOT NULL
)
"""


class LegacyNotesInitializationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self._db_index = 0

    # ---- 命令执行与断言辅助 ----

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def list_notes(self, db_path, contact_id):
        return self.run_crm(db_path, "list-notes", "--id", str(contact_id))

    def add_note(self, db_path, contact_id, text):
        return self.run_crm(
            db_path, "add-note", "--id", str(contact_id), "--text", text
        )

    def assert_success(self, result):
        """成功调用：退出码 0、标准错误为空、无堆栈。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(b"Traceback", result.stderr)

    def assert_rejected(self, result, expected_stderr_line):
        """拒绝调用：退出码 2、标准输出为空、标准错误恰为单行加换行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )
        self.assertNotIn(b"Traceback", result.stderr)

    # ---- 既有库样例 ----

    def create_legacy_db(self, name=None):
        """构造仅有当前格式 contacts 表（含自增编号信息）的既有数据库。

        显式插入编号 7、11、15 三条联系人，使 sqlite_sequence 记录
        联系人序列已用到 15；不创建 notes 表。每次调用使用独立文件。
        """
        if name is None:
            self._db_index += 1
            name = f"legacy-{self._db_index}.sqlite3"
        db_path = self.tmpdir / name
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(LEGACY_CONTACTS_DDL)
            conn.executemany(
                "INSERT INTO contacts (id, name, email, company)"
                " VALUES (?, ?, ?, ?)",
                [
                    (contact["id"], contact["name"], contact["email"], contact["company"])
                    for contact in SEED_CONTACTS
                ],
            )
            conn.commit()
        finally:
            conn.close()
        return db_path

    def assert_notes_table_absent(self, db_path):
        """notes 表在数据库中尚不存在（sqlite_master 查不到）。"""
        with sqlite3.connect(db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT name FROM sqlite_master"
                    " WHERE type='table' AND name='notes'"
                ).fetchall(),
                [],
            )

    def assert_notes_table_exists(self, db_path):
        with sqlite3.connect(db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT name FROM sqlite_master"
                    " WHERE type='table' AND name='notes'"
                ).fetchall(),
                [("notes",)],
            )

    def assert_contacts_preserved(self, db_path):
        """三个联系人的编号、完整字段与数量及自增编号信息均未改变。"""
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, email, company FROM contacts ORDER BY id ASC"
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    (contact["id"], contact["name"], contact["email"], contact["company"])
                    for contact in SEED_CONTACTS
                ],
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
                len(SEED_CONTACTS),
            )
            # AUTOINCREMENT 的自增编号信息原样保留：联系人序列仍记为 15，
            # 备注序列仅在备注表被使用后才出现。
            sequence = dict(
                conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall()
            )
            self.assertEqual(sequence.get("contacts"), SEED_MAX_ID)

    def assert_public_contacts_unchanged(self, db_path):
        """通过公开命令复查三名联系人的完整资料与按公司分组均不变。"""
        expected_note = {
            "id": 1,
            "contact_id": LIN_ID,
            "text": FIRST_NOTE_TEXT,
        }

        # 各编号 get 返回完整联系人 JSON
        for contact in SEED_CONTACTS:
            result = self.run_crm(db_path, "get", "--id", str(contact["id"]))
            self.assert_success(result)
            self.assertEqual(json.loads(result.stdout.decode("utf-8")), contact)

        # 按公司查询：星河科技含林宁、许禾并按编号升序；远帆咨询只有周岚
        result_xinghe = self.run_crm(db_path, "list", "--company", "星河科技")
        self.assert_success(result_xinghe)
        self.assertEqual(
            json.loads(result_xinghe.stdout.decode("utf-8")), [LIN, XU]
        )

        result_yuanfan = self.run_crm(db_path, "list", "--company", "远帆咨询")
        self.assert_success(result_yuanfan)
        self.assertEqual(
            json.loads(result_yuanfan.stdout.decode("utf-8")), [ZHOU]
        )

        # 备注归属不受联系人复查影响
        result_lin_notes = self.list_notes(db_path, LIN_ID)
        self.assert_success(result_lin_notes)
        self.assertEqual(
            json.loads(result_lin_notes.stdout.decode("utf-8")), [expected_note]
        )
        for other_id in (XU_ID, ZHOU_ID):
            result = self.list_notes(db_path, other_id)
            self.assert_success(result)
            self.assertEqual(result.stdout.decode("utf-8"), "[]\n")

    # ---- 查询先发生：list-notes 触发补表 ----

    def test_list_notes_initializes_notes_table_then_add_note_works(self):
        db_path = self.create_legacy_db("query-first.sqlite3")
        self.assert_notes_table_absent(db_path)

        # 首次访问即 list-notes：先补建 notes 表，林宁尚无备注，输出 []
        first_query = self.list_notes(db_path, LIN_ID)
        self.assert_success(first_query)
        self.assertEqual(first_query.stdout.decode("utf-8"), "[]\n")
        self.assert_notes_table_exists(db_path)

        # 随后追加“ 首次联系 ”：单对象，备注编号 1、contact_id 7、
        # 正文仅去掉首尾空白
        add_result = self.add_note(db_path, LIN_ID, FIRST_NOTE_RAW)
        self.assert_success(add_result)
        note = json.loads(add_result.stdout.decode("utf-8"))
        self.assertIsInstance(note, dict)
        self.assertEqual(
            note,
            {"id": 1, "contact_id": LIN_ID, "text": FIRST_NOTE_TEXT},
        )

        # 新的独立命令调用重新查询：只有这一条备注，重复查询不清空
        expected_note = {"id": 1, "contact_id": LIN_ID, "text": FIRST_NOTE_TEXT}
        for _ in range(2):
            result = self.list_notes(db_path, LIN_ID)
            self.assert_success(result)
            self.assertEqual(
                result.stdout.decode("utf-8"),
                json.dumps([expected_note], ensure_ascii=False) + "\n",
            )

        # 许禾、周岚仍返回空数组
        for other_id in (XU_ID, ZHOU_ID):
            result = self.list_notes(db_path, other_id)
            self.assert_success(result)
            self.assertEqual(result.stdout.decode("utf-8"), "[]\n")

        # 三个联系人的编号、完整字段与数量未变
        self.assert_contacts_preserved(db_path)
        self.assert_public_contacts_unchanged(db_path)

    # ---- 追加先发生：add-note 触发补表 ----

    def test_add_note_initializes_notes_table_on_first_use(self):
        db_path = self.create_legacy_db("add-first.sqlite3")
        self.assert_notes_table_absent(db_path)

        # 首次备注操作直接追加：补建 notes 表并写入，结果与查询先发生一致
        add_result = self.add_note(db_path, LIN_ID, FIRST_NOTE_RAW)
        self.assert_success(add_result)
        self.assertEqual(
            add_result.stdout.decode("utf-8"),
            json.dumps(
                {"id": 1, "contact_id": LIN_ID, "text": FIRST_NOTE_TEXT},
                ensure_ascii=False,
            )
            + "\n",
        )
        self.assert_notes_table_exists(db_path)

        # 新的独立命令调用重新查询：编号 7 仅这条备注，11/15 仍为 []
        expected_note = {"id": 1, "contact_id": LIN_ID, "text": FIRST_NOTE_TEXT}
        result = self.list_notes(db_path, LIN_ID)
        self.assert_success(result)
        self.assertEqual(
            json.loads(result.stdout.decode("utf-8")), [expected_note]
        )

        result_repeat = self.list_notes(db_path, LIN_ID)
        self.assert_success(result_repeat)
        self.assertEqual(
            json.loads(result_repeat.stdout.decode("utf-8")), [expected_note]
        )

        for other_id in (XU_ID, ZHOU_ID):
            result = self.list_notes(db_path, other_id)
            self.assert_success(result)
            self.assertEqual(result.stdout.decode("utf-8"), "[]\n")

        # 旧资料完整保留
        self.assert_contacts_preserved(db_path)
        self.assert_public_contacts_unchanged(db_path)

    # ---- 初始化边界：校验失败不补表 ----

    def test_invalid_id_before_initialization_does_not_create_notes_table(self):
        db_path = self.create_legacy_db("invalid-id.sqlite3")
        self.assert_notes_table_absent(db_path)

        result = self.list_notes(db_path, 0)
        self.assert_rejected(result, ID_ERROR_LINE)

        # 编号校验先于数据库访问：notes 表仍不存在，旧资料不变
        self.assert_notes_table_absent(db_path)
        self.assert_contacts_preserved(db_path)

        # 再经合法查询：林宁仍无备注，此时才补表
        query = self.list_notes(db_path, LIN_ID)
        self.assert_success(query)
        self.assertEqual(query.stdout.decode("utf-8"), "[]\n")
        self.assert_notes_table_exists(db_path)
        self.assert_contacts_preserved(db_path)

    def test_blank_text_before_initialization_does_not_create_notes_table(self):
        db_path = self.create_legacy_db("blank-text.sqlite3")
        self.assert_notes_table_absent(db_path)

        result = self.add_note(db_path, LIN_ID, "   ")
        self.assert_rejected(result, TEXT_ERROR_LINE)

        # 正文校验先于数据库访问：notes 表仍不存在，旧资料不变
        self.assert_notes_table_absent(db_path)
        self.assert_contacts_preserved(db_path)

        # 再追加合法备注：备注编号仍从 1 开始，说明失败未占用序列
        add_result = self.add_note(db_path, LIN_ID, FIRST_NOTE_RAW)
        self.assert_success(add_result)
        self.assertEqual(
            json.loads(add_result.stdout.decode("utf-8")),
            {"id": 1, "contact_id": LIN_ID, "text": FIRST_NOTE_TEXT},
        )
        self.assert_contacts_preserved(db_path)

    # ---- 初始化边界：合法参数但联系人不存在，先补表再失败 ----

    def test_unknown_id_initializes_notes_table_then_reports_not_found(self):
        db_path = self.create_legacy_db("unknown-id.sqlite3")
        self.assert_notes_table_absent(db_path)
        # 样例最大编号 15，99 必然不存在
        self.assertLess(SEED_MAX_ID, UNKNOWN_ID)

        result = self.list_notes(db_path, UNKNOWN_ID)
        self.assert_rejected(result, NOT_FOUND_LINE)

        # 先初始化备注表（空表），再以联系人不存在失败
        self.assert_notes_table_exists(db_path)
        with sqlite3.connect(db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0
            )
        self.assert_contacts_preserved(db_path)

        # 三个联系人仍可正常查询，且均无备注；失败未写入任何备注
        for contact in SEED_CONTACTS:
            query = self.list_notes(db_path, contact["id"])
            self.assert_success(query)
            self.assertEqual(query.stdout.decode("utf-8"), "[]\n")
        self.assert_contacts_preserved(db_path)


if __name__ == "__main__":
    unittest.main()
