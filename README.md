# 本地客户关系管理台：联系人新增与按公司筛选入门

本指南介绍最常用的两个操作：**新增联系人**与**按公司筛选联系人**。
程序仅使用 Python 3 标准库（argparse、json、sqlite3 等），联系人数据保存在本地
SQLite 数据库文件中，无需安装任何第三方依赖，也不需要启动服务。

本文档中的输出均为与当前命令行为一致的**预期结果**，供对照使用。

## 1. 运行环境与调用方式

- 需要 Python 3，无第三方依赖。
- 所有命令都从 `crm.py` 所在目录调用，例如：

  ```console
  python3 crm.py --db demo.sqlite3 <子命令> ...
  ```

- `--db <数据库文件路径>` 是**必填参数，且必须写在子命令之前**
  （即 `--db demo.sqlite3 add ...` 正确；写成 `add --db demo.sqlite3 ...`
  会被拒绝并报错退出）。
- 数据库文件的**父目录必须已经存在**；程序不会代为创建目录。
- 数据库文件**不存在时**，一次有效的请求会自动初始化它（建表）；
  文件**已存在时**直接复用，其中已有数据保持不变。

## 2. 固定样例：向全新的 demo.sqlite3 新增三名联系人

下面的样例使用一个全新的数据库文件 `demo.sqlite3`。若该文件已存在，请先删除它
（或改用另一个文件名），以得到编号依次为 1、2、3 的预期结果。

依次执行三条新增命令：

```console
python3 crm.py --db demo.sqlite3 add --name 林宁 --email lin@example.test --company 星河科技
python3 crm.py --db demo.sqlite3 add --name 周岚 --email zhou@example.test --company 远帆咨询
python3 crm.py --db demo.sqlite3 add --name 许禾 --email xu@example.test --company 星河科技
```

`add` 在标准输出打印**新增的单个联系人对象**，退出码为 0，标准错误为空。
三次调用的预期输出依次为：

```json
{"id": 1, "name": "林宁", "email": "lin@example.test", "company": "星河科技"}
```

```json
{"id": 2, "name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"}
```

```json
{"id": 3, "name": "许禾", "email": "xu@example.test", "company": "星河科技"}
```

全新数据库中，编号（`id`）按新增顺序依次为 1、2、3。每条记录包含四个字段：
`id`、`name`、`email`、`company`。

## 3. 按公司筛选查询

使用 `list --company <公司名>` 按公司筛选。公司名会先去除首尾空白，再做
**精确匹配且区分大小写**的比较；结果以 JSON **数组**输出，按 `id` 升序排列，
退出码为 0，标准错误为空。

查询星河科技（预期返回林宁和许禾，共两条，按编号升序）：

```console
python3 crm.py --db demo.sqlite3 list --company 星河科技
```

预期输出：

```json
[{"id": 1, "name": "林宁", "email": "lin@example.test", "company": "星河科技"}, {"id": 3, "name": "许禾", "email": "xu@example.test", "company": "星河科技"}]
```

查询远帆咨询（预期只返回周岚一条）：

```console
python3 crm.py --db demo.sqlite3 list --company 远帆咨询
```

预期输出：

```json
[{"id": 2, "name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"}]
```

没有任何联系人属于该公司时，返回空数组（退出码仍为 0）：

```console
python3 crm.py --db demo.sqlite3 list --company 不存在的公司
```

预期输出：

```json
[]
```

公司筛选参数**可以省略**：省略 `--company` 时查询**全部公司**的联系人
（而不是要求公司必填）：

```console
python3 crm.py --db demo.sqlite3 list
```

预期输出全部三条记录，按编号升序：

```json
[{"id": 1, "name": "林宁", "email": "lin@example.test", "company": "星河科技"}, {"id": 2, "name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"}, {"id": 3, "name": "许禾", "email": "xu@example.test", "company": "星河科技"}]
```

## 4. 持久化：在后续独立调用中再次查到

每次调用都是相互独立的进程，联系人保存在 `--db` 指定的 SQLite 文件中。
因此新增完成后，重新执行一次第 3 节中的查询命令（哪怕换一个终端会话），
仍能查到同样的记录——这说明数据已落盘，而不是只存在于单次运行的内存里。

## 5. 在已有数据库上使用

若 `--db` 指向一个已有数据库，程序直接复用该文件，不会清空或重建数据。
此时新联系人的编号**不一定从 1 开始**，请以各条 `add` 输出对象中的实际
`id` 为准，再用该编号或公司名进行后续查询。

## 6. 字段清理与匹配规则

- 新增的 `name`、`email`、`company` 只去除**首尾空白**；
  字符串**内部的字符与大小写原样保留**。例如传入 `" 林 宁 "`、
  `" lin2@example.test "`、`" 星河 科技 "`，存储结果分别为
  `林 宁`、`lin2@example.test`、`星河 科技`。
- `list --company` 的筛选值同样先去除首尾空白，再与库中公司名
  **精确、区分大小写**地比较。因此 `星河科技` 不会匹配 `星河`，
  `Acme` 不会匹配 `acme`；但首尾空白不影响匹配，`" 星河科技 "`
  经清理后与库中的 `星河科技` 相等，仍会命中。

## 7. 失败情况

下列失败均以**退出码 2**结束，**标准输出为空**，错误信息写入**标准错误**。
字段校验在连接数据库之前进行，因此**字段无效时不会创建新的数据库文件，
也不会改变已有数据库中的任何联系人**。

| 失败情形 | 命令示例 | 标准错误中的预期输出 |
| --- | --- | --- |
| 姓名仅含空白 | `python3 crm.py --db demo.sqlite3 add --name "   " --email a@b.co --company 星河科技` | `name: must not be empty` |
| 邮箱缺少 `@` | `python3 crm.py --db demo.sqlite3 add --name 测试 --email abc.example --company 星河科技` | `email: invalid email address` |
| 公司仅含空白 | `python3 crm.py --db demo.sqlite3 add --name 测试 --email a@b.co --company "  "` | `company: must not be empty` |
| 父目录不存在（业务输入有效） | `python3 crm.py --db 不存在的目录/demo.sqlite3 add --name 测试 --email a@b.co --company 星河科技` | `db: parent directory does not exist` |

例如，姓名仅含空白时，标准错误中的完整一行为：

```text
name: must not be empty
```

## 8. 本指南未展开的其他功能

`crm.py` 还支持按编号查看（get）、按编号更新姓名/邮箱/公司、删除、
按公司汇总数量、备注的追加与查看，以及列表的其他筛选与输出选项等。
这些功能的命令、数据格式与流程本入门指南不展开，请以程序自带的命令行帮助
（`python3 crm.py -h` 及各子命令的 `-h`）和仓库中的对应流程说明文档为准。
