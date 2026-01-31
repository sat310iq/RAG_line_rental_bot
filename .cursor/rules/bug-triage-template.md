# 🐞 Bug Triage Task

## Objective
- "原因の特定" または "再現条件の確立" のどちらをゴールにするか明記

## Fixed Sequence（順序固定）
1) Observed / Expected を分離
2) Repro steps を最小化（MRE）
3) Hypotheses ≥ 3
4) 反証テストを先に走らせる
5) 証拠が揃ったら修正
6) 再発防止テスト追加
7) Incident log（INC）更新

## Hypothesis Table（必須）
- H1:
  - evidence for:
  - evidence against:
  - falsification test:
- H2:
  - evidence for:
  - evidence against:
  - falsification test:
- H3:
  - evidence for:
  - evidence against:
  - falsification test:

## Acceptance Criteria
- 再現手順が誰でも出来る
- 原因が特定できるか、少なくとも原因候補が2つまで絞れる
- 修正した場合：回帰テストが追加され、落ちていたテストが通る

---

## 使用例

### Objective
- 原因の特定: `test_tenant_auth`テストが失敗する原因を特定し、修正する

### Observed / Expected
- **Observed**: `test_tenant_auth`が`assert None is not None`で失敗
- **Expected**: テストが正常に通過する

### Repro steps（MRE）
```bash
pytest tests/test_tenant_auth.py::test_tenant_auth -v
```

### Hypothesis Table
- **H1**: `TenantAuth._load_tenant_master()`が認証テーブルを使用しない実装に変更された
  - evidence for: コードレビューで実装変更を確認
  - evidence against: テストが以前は通っていた
  - falsification test: `TenantAuth._load_tenant_master()`の実装を確認
- **H2**: テストが古い実装を前提としている
  - evidence for: テストコードが`_tenants`が空でないことを期待している
  - evidence against: 実装が意図的に変更された可能性
  - falsification test: テストコードと実装コードの整合性を確認
- **H3**: 環境変数や設定ファイルが不足している
  - evidence for: 認証テーブルへの接続情報が必要な可能性
  - evidence against: エラーメッセージに接続エラーがない
  - falsification test: 環境変数と設定ファイルを確認

### Acceptance Criteria
- [ ] 再現手順が明確に文書化されている
- [ ] 原因が特定できた、または候補が2つまで絞れた
- [ ] 修正後、回帰テストが追加され、テストが通過する
- [ ] `docs/incident/INC-xxxx.md`が更新されている
