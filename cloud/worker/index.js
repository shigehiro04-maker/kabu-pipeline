// 株分析の日次更新を、決まった時刻に GitHub Actions で始めさせる Cloudflare Worker。
// GitHub の定時実行（schedule）は混むと何時間も遅れるため、Cloudflare の定時実行（Cron Triggers）から
// workflow_dispatch（auto=true）で起動する。鍵 GH_TOKEN は kabu-pipeline の Actions 読み書きだけの権限。
//   設定: wrangler.toml（時刻は UTC。06:40 = 日本時間 15:40、11:40 = 20:40）
//   鍵の登録: npx wrangler secret put GH_TOKEN
const REPO = "shigehiro04-maker/kabu-pipeline";
const WORKFLOW = "daily.yml";

async function dispatch(env) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GH_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "kabu-dispatch-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs: { auto: "true" } }),
  });
  if (r.status !== 204) {
    throw new Error(`GitHub への起動依頼に失敗: ${r.status} ${await r.text()}`);
  }
  console.log(`起動しました: ${new Date().toISOString()}`);
}

export default {
  async scheduled(event, env, ctx) {
    // 一時的な失敗に備えて3回まで試す
    for (let i = 1; i <= 3; i++) {
      try { await dispatch(env); return; }
      catch (e) { console.log(`${i}回目: ${e.message}`); if (i === 3) throw e; await new Promise(r => setTimeout(r, 20000)); }
    }
  },
};
