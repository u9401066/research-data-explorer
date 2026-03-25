# Progress (Updated: 2026-03-26)

## Done

- 新增 repo 與 extension 的 Apache-2.0 license 檔案
- 在 CI 加入 VS Code extension 的 lint、test、VSIX package 與 artifact upload
- 新增 tag 驅動的 marketplace/Open VSX 發布 workflow
- 補上 extension ESLint 設定並清掉 release 驗證的 lint blocker
- 完成 extension lint、test、package 驗證並產出 research-data-explorer-0.1.0.vsix
- 建立 CHANGELOG.md 並補上 0.1.0 release 記錄骨架
- 加入 release consistency pre-commit hook，強制 repo/VSX 版本同步與 changelog 覆蓋
- 將內部測試 Excel 加入 gitignore 並在 hook 中阻止誤提交
- 修正 Windows pre-commit 編碼與 lockfile 誤報問題
- 驗證全 repo pytest 與 pre-commit 皆通過
- 已切到 feature/extension-release-0.1.0，第一包 release 相關檔案已 staged

## Doing

- 準備依三包切分提交，之後 push feature branch，等待 merge 後再打 v0.1.0 tag

## Next

- 若要正式發版，設定 GitHub secrets VSCE_PAT 與 OVSX_PAT
- 完成第二包與第三包 staged/commit
- push feature/extension-release-0.1.0 並等待 CI/PR
- merge 到 main 後建立並 push v0.1.0 tag
