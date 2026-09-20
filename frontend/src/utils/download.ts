/**
 * utils/download.ts —— 把一个字符串存成文件（导出会话时用）。
 *
 * 为什么不用 Electron 主进程的「保存到…」对话框：
 *   那需要新增一条 IPC 通道 + 改 preload + 重新打包桌面端；
 *   而浏览器标准的 Blob + `<a download>` 在 Electron 的渲染进程里同样有效
 *   （Chromium 会走下载流程）。一条路两种运行环境都能用，代码也只有十几行。
 *
 * 代价：用户拿不到"选保存位置"的机会，文件会落到系统的下载目录
 *       （或被 Electron 的下载策略接管），所以调用方要提示文件名。
 */

/**
 * 把文本内容存成本地文件。
 *
 * 步骤（每一步都不能省）：
 *   1. new Blob 把字符串包成二进制，并指定 MIME —— 否则中文可能被当成未知编码
 *   2. URL.createObjectURL 造一个临时 blob: 地址给 <a href> 用
 *   3. 造一个不可见的 <a>，点它（这是唯一能触发浏览器下载的途径）
 *   4. 立刻 revoke 掉临时地址，否则这段内存会一直挂着
 *
 * @param filename 建议的文件名（含扩展名），如 "会话标题-20261021-1043.md"
 * @param content 文件全文（UTF-8 文本）
 * @param mime MIME 类型；md 用 text/markdown，json 用 application/json
 */
export function download_text_file(
  filename: string,
  content: string,
  mime = 'text/markdown;charset=utf-8',
): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  // download 属性告诉浏览器"别打开，存下来"，值就是建议文件名
  link.download = filename
  // 挂到文档上再点：部分浏览器对脱离文档的 <a> 不触发下载
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
