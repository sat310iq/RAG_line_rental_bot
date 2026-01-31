# Beadsタスク作成 - Planモード用ルール

## PlanモードでのBeadsタスク作成手順

PlanモードでBeadsタスクを作成する際は、以下の手順に従ってください。

---

## 1. タスクタイプの判定

まず、作成するタスクが**通常タスク**か**バグ調査**かを判定します：

- **通常タスク**: 新機能実装、改善、リファクタリングなど
- **バグ調査**: バグの原因特定、障害対応、テスト失敗の修正など

---

## 2. テンプレートの選択

### 通常タスクの場合
`.cursor/rules/beads-task-template.md`を使用

### バグ調査の場合
`.cursor/rules/bug-triage-template.md`を使用

---

## 3. タスク作成のワークフロー

### Step 1: テンプレートに基づいてdescriptionを生成

ユーザーから以下の情報を取得：
- Objective（目的）
- Context（現状・背景）
- Constraints（制約条件）
- Files touched（変更予定のファイル、分かれば）

### Step 2: テンプレートに従って構造化されたdescriptionを作成

選択したテンプレートの全セクションを埋めて、Markdown形式のdescriptionを生成します。

**重要**: 
- テンプレートの**すべてのセクション**を含める
- 各セクションに具体的な内容を記入
- 仮説は最低3つ（バグ調査の場合）
- テスト計画は先に書く

### Step 3: Beads Issueとして作成

`bd create`コマンドを使用してIssueを作成します。

**コマンド形式**:
```bash
bd create --title="[タイトル]" --type=[task|bug] --priority=[0|1|2] --description="[テンプレートに基づく完全なdescription]"
```

**注意**: `bd create`コマンドが使えない場合は、`.beads/issues.jsonl`に直接JSON Lines形式で追加します。

---

## 4. JSON Lines形式での直接作成（bdコマンドが使えない場合）

`bd`コマンドが使えない場合は、`.beads/issues.jsonl`に直接追加します。

### フォーマット

```json
{
  "id": "[プロジェクト名]-[ランダム3文字]",
  "title": "[タイトル]",
  "description": "[テンプレートに基づく完全なMarkdown description]",
  "status": "open",
  "priority": [0|1|2],
  "issue_type": "task" | "bug",
  "created_at": "[ISO 8601形式の日時]",
  "created_by": "skoyama",
  "updated_at": "[ISO 8601形式の日時]"
}
```

### ID生成ルール
- プロジェクト名: `rental_rag_poc`
- ランダム3文字: 小文字英数字（例: `4cb`, `9b3`, `340`）
- 例: `rental_rag_poc-4cb`

### 日時フォーマット
- ISO 8601形式: `2026-01-28T23:29:51.128706+09:00`
- タイムゾーン: `+09:00` (JST)

---

## 5. Planモードでの実行例

### 例1: 通常タスクの作成

**入力**:
- Objective: 検索精度をRecall@5: 0.25 → 0.50+に改善する
- Context: 現在の評価結果で検索失敗率が70%、5件の質問で検索結果が空
- Constraints: 既存のRouter/Planner/Reranking設計を壊さない
- Files touched: `src/rag_answerer.py`, `src/vector_store_manager.py`

**実行**:
1. `beads-task-template.md`を読み込む
2. テンプレートに基づいてdescriptionを生成
3. `bd create --title="検索精度の改善（Recall@5: 0.25 → 0.50+）" --type=task --priority=1 --description="[生成したdescription]"`

### 例2: バグ調査タスクの作成

**入力**:
- Objective: test_tenant_authテストが失敗する原因を特定し、修正する
- Observed: `assert None is not None`で失敗
- Expected: テストが正常に通過する
- Repro steps: `pytest tests/test_tenant_auth.py::test_tenant_auth -v`

**実行**:
1. `bug-triage-template.md`を読み込む
2. テンプレートに基づいてdescriptionを生成（Hypothesis Table含む）
3. `bd create --title="test_tenant_authテストの修正" --type=bug --priority=2 --description="[生成したdescription]"`

---

## 6. チェックリスト

タスク作成時に以下を確認：

- [ ] 適切なテンプレートを選択したか（通常タスク vs バグ調査）
- [ ] テンプレートの全セクションが埋まっているか
- [ ] Objectiveが1文で明確に書かれているか
- [ ] Success Criteria（Must/Should/Kill Criteria）が定義されているか
- [ ] Decision Hygiene Protocolが含まれているか
- [ ] 仮説が3つ以上あるか（バグ調査の場合）
- [ ] テスト計画が先に書かれているか
- [ ] 適切なpriorityが設定されているか（0=最高, 1=高, 2=中）
- [ ] issue_typeが正しいか（task vs bug）

---

## 7. 優先度のガイドライン

- **P0（最高）**: システム停止、セキュリティ問題、データ損失リスク
- **P1（高）**: 主要機能の不具合、パフォーマンス問題、ユーザー体験への重大な影響
- **P2（中）**: 改善タスク、ドキュメント更新、テスト追加、軽微なバグ

---

## 8. テンプレートファイルの場所

- 通常タスク: `.cursor/rules/beads-task-template.md`
- バグ調査: `.cursor/rules/bug-triage-template.md`

これらのファイルは必ず読み込んでから使用してください。

---

## 9. Planモードでのプロンプト例

### 通常タスク作成のプロンプト

```
PlanモードでBeadsタスクを作成してください。

タスク情報:
- Objective: [目的を1文で]
- Context: [現状・背景]
- Constraints: [制約条件]
- Files touched: [変更予定のファイル、分かれば]

手順:
1. .cursor/rules/beads-task-template.mdを読み込む
2. テンプレートに基づいて完全なdescriptionを生成（全セクションを含める）
3. bd createコマンドでIssueを作成（使えない場合はissues.jsonlに直接追加）
```

### バグ調査タスク作成のプロンプト

```
PlanモードでBeadsバグ調査タスクを作成してください。

バグ情報:
- Objective: [原因の特定 または 再現条件の確立]
- Observed: [観測された現象]
- Expected: [期待される動作]
- Repro steps: [再現手順]

手順:
1. .cursor/rules/bug-triage-template.mdを読み込む
2. テンプレートに基づいて完全なdescriptionを生成（Hypothesis Table含む、仮説3つ以上）
3. bd createコマンドでIssueを作成（使えない場合はissues.jsonlに直接追加）
```

---

## 10. 自動実行のためのAI指示

Planモードでタスク作成を依頼された場合、AIは以下を自動的に実行する必要があります：

1. **テンプレートファイルの読み込み**
   - `read_file`ツールで適切なテンプレートを読み込む
   - タスクタイプに応じて選択（通常タスク vs バグ調査）

2. **テンプレートへの情報埋め込み**
   - ユーザーから提供された情報をテンプレートの各セクションに埋める
   - 不足している情報は推測または質問する

3. **完全なdescriptionの生成**
   - テンプレートの全セクションを含めたMarkdown形式のdescriptionを生成
   - 仮説が3つ以上あることを確認（バグ調査の場合）

4. **Issueの作成**
   - `bd create`コマンドを試行
   - 失敗した場合は`.beads/issues.jsonl`に直接追加
   - JSON Lines形式で正しいフォーマットを維持

5. **確認と報告**
   - 作成したIssueのIDとタイトルを報告
   - テンプレートの全セクションが含まれていることを確認
