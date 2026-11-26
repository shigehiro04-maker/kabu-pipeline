// 株分析の日次更新を、決まった時刻に GitHub Actions で始めさせる Cloudflare Worker。
// GitHub の定時実行（schedule）は混むと何時間も遅れるため、Cloudflare の定時実行（Cron Triggers）から
// workflow_dispatch（auto=true）で起動する。鍵 GH_TOKEN は kabu-pipeline の Actions 読み書きだけの権限。
//   設定: wrangler.toml（時刻は UTC。06:40 = 日本時間 15:40、11:40 = 20:40、22:30 = 翌朝 7:30）
//   鍵の登録: npx wrangler secret put GH_TOKEN
const REPO = "shigehiro04-maker/kabu-pipeline";
// 定時実行の時刻（UTC の cron 式）→ 動かすワークフロー
const WORKFLOWS = {
  "40 6 * * MON-FRI": "daily.yml",      // 東証 15:40
  "40 11 * * MON-FRI": "daily.yml",     // 東証 20:40
  "30 22 * * MON-FRI": "us_daily.yml",  // 米国 7:30（日本時間の火〜土）
};

async function dispatch(env, wf) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${wf}/dispatches`, {
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
  console.log(`起動しました: ${wf} ${new Date().toISOString()}`);
}

export default {
  async scheduled(event, env, ctx) {
    // 一時的な失敗に備えて3回まで試す
    const wf = WORKFLOWS[event.cron] || "daily.yml";
    for (let i = 1; i <= 3; i++) {
      try { await dispatch(env, wf); return; }
      catch (e) { console.log(`${i}回目: ${e.message}`); if (i === 3) throw e; await new Promise(r => setTimeout(r, 20000)); }
    }
  },
};
