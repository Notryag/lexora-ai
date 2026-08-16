import { expect, test } from "@playwright/test";

const caseId = "018f6f7c-3500-7c4a-83e7-64dd8aa83291";
const materialId = "018f6f7c-3500-7c4a-83e7-64dd8aa83292";
const threadId = "018f6f7c-3500-7c4a-83e7-64dd8aa83293";
const runId = "018f6f7c-3500-7c4a-83e7-64dd8aa83294";
const persistedActivityHistory = {
  run_id: runId,
  status: "completed",
  completed_at: "2026-08-08T00:00:03Z",
  activities: [
    {
      seq: 1,
      type: "task_started",
      event_type: "subagent.start",
      subagent_type: "legal_researcher",
      task_id: "research-task",
    },
    {
      seq: 2,
      type: "tool_started",
      event_type: "tool.started",
      tool_name: "search_legal_authorities",
      call_id: "authority-search-1",
      caller: "subagent:legal_researcher",
    },
    {
      seq: 3,
      type: "tool_completed",
      event_type: "tool.completed",
      tool_name: "search_legal_authorities",
      call_id: "authority-search-1",
      caller: "subagent:legal_researcher",
    },
    {
      seq: 4,
      type: "task_completed",
      event_type: "subagent.end",
      subagent_type: "legal_researcher",
      task_id: "research-task",
      status: "completed",
    },
  ],
};

test("persists material and continues a cited legal conversation", async ({ page }) => {
  const conversationRequests: string[] = [];
  const resumeRequests: Array<{ method: string; lastEventId: string | null }> = [];
  let created = false;
  let materialAdded = false;
  let profile = {
    case_type: null as string | null,
    parties: [] as string[],
    claims: [] as string[],
    key_facts: [] as string[],
    disputed_issues: [] as string[],
    evidence_notes: [] as string[],
    missing_information: [] as string[],
  };
  const messages: Array<Record<string, unknown>> = [];
  const persistedCase = {
    id: caseId,
    title: "未命名案件",
    background: null,
    profile,
    material_count: 1,
    created_at: "2026-08-08T00:00:00Z",
    updated_at: "2026-08-08T00:00:00Z",
  };

  await page.route("**/api/v1/cases**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path.includes("/messages") || path.endsWith("/run")) {
      conversationRequests.push(`${method} ${path}`);
    }

    if (path.endsWith(`/runs/${runId}/events/stream`) && method === "GET") {
      resumeRequests.push({
        method,
        lastEventId: request.headers()["last-event-id"] ?? null,
      });
      await route.fulfill({
        contentType: "text/event-stream",
        body: [
          sse("messages", {
            delta: "支持拖欠工资的初步主张 [M1:C1]，工资支付规则见 [L1234567890abcdef:C30]。",
          }, "0-9"),
          sse("complete", { result: {
            case_id: caseId,
            thread_id: threadId,
            run_id: runId,
            assistant_message: messages[1].content as string,
            material_count: 1,
            legal_citations: messages[1].legal_citations,
            case_law_citations: [],
            profile_updated: true,
            case_profile: profile,
          } }, "0-10"),
          sse("end", {}),
        ].join(""),
      });
      return;
    }

    if (path === "/api/v1/cases" && method === "GET") {
      await route.fulfill({ json: created ? [persistedCase] : [] });
      return;
    }
    if (path === "/api/v1/cases" && method === "POST") {
      created = true;
      await route.fulfill({ status: 201, json: persistedCase });
      return;
    }
    if (path.endsWith("/profile") && method === "PUT") {
      profile = request.postDataJSON();
      persistedCase.profile = profile;
      await route.fulfill({ json: persistedCase });
      return;
    }
    if (path.endsWith("/materials") && method === "GET") {
      await route.fulfill({
        json: materialAdded
          ? [{
              material_id: materialId,
              case_id: caseId,
              title: "工资记录",
              kind: "evidence",
              content: "公司连续三个月拖欠工资。",
              created_at: "2026-08-08T00:00:00Z",
            }]
          : [],
      });
      return;
    }
    if (path.endsWith("/materials") && method === "POST") {
      materialAdded = true;
      await route.fulfill({
        status: 201,
        json: {
          material_id: materialId,
          case_id: caseId,
          title: "工资记录",
          kind: "evidence",
          content: "公司连续三个月拖欠工资。",
          created_at: "2026-08-08T00:00:00Z",
        },
      });
      return;
    }
    if (path.endsWith("/messages") && method === "GET") {
      await route.fulfill({ json: messages });
      return;
    }
    if (path.endsWith("/run/activities") && method === "GET") {
      await route.fulfill({ json: persistedActivityHistory });
      return;
    }
    if (path.endsWith("/messages/stream") && method === "POST") {
      profile = {
        ...profile,
        key_facts: [...profile.key_facts, "公司连续三个月拖欠工资"],
      };
      persistedCase.profile = profile;
      messages.push(
        {
          id: "018f6f7c-3500-7c4a-83e7-64dd8aa83295",
          thread_id: threadId,
          run_id: runId,
          role: "user",
          content: "公司拖欠工资怎么办？",
          legal_citations: [],
          created_at: "2026-08-08T00:00:01Z",
        },
        {
          id: "018f6f7c-3500-7c4a-83e7-64dd8aa83296",
          thread_id: threadId,
          run_id: runId,
          role: "assistant",
          content: "现有工资记录能够支持拖欠工资的初步主张 [M1:C1]，工资支付规则见 [L1234567890abcdef:C30]。",
          legal_citations: [
            {
              reference: "L1234567890abcdef:C30",
              title: "中华人民共和国劳动合同法",
              article_label: "第三十条",
              issuing_authority: "全国人民代表大会常务委员会",
              source_url: "https://flk.npc.gov.cn/detail?id=test",
              status: "effective",
            },
            {
              reference: "L1234567890abcdef:C50",
              title: "未在正文使用的法规",
              article_label: "第五十条",
              issuing_authority: "全国人民代表大会常务委员会",
              source_url: "https://flk.npc.gov.cn/detail?id=unused",
              status: "effective",
            },
          ],
          created_at: "2026-08-08T00:00:02Z",
        },
      );
      await route.fulfill({
        contentType: "text/event-stream",
        body: [
          sse("metadata", { run_id: runId, thread_id: threadId }, "0-0"),
          sse("custom", {
            type: "tool_started",
            event_type: "tool.started",
            tool_name: "delegate_legal_researcher",
            call_id: "research-task",
          }, "0-1"),
          sse("custom", {
            type: "task_started",
            event_type: "subagent.start",
            subagent_type: "legal_researcher",
            task_id: "research-task",
          }, "0-2"),
          sse("custom", {
            type: "tool_started",
            event_type: "tool.started",
            tool_name: "search_legal_authorities",
            call_id: "authority-search-1",
            caller: "subagent:legal_researcher",
          }, "0-3"),
          sse("custom", {
            type: "tool_completed",
            event_type: "tool.completed",
            tool_name: "search_legal_authorities",
            call_id: "authority-search-1",
            caller: "subagent:legal_researcher",
          }, "0-4"),
          sse("custom", {
            type: "task_running",
            event_type: "subagent.step",
            tool_name: "search_legal_authorities",
            task_id: "research-task",
            kind: "tool",
          }, "0-5"),
          sse("custom", {
            type: "tool_completed",
            event_type: "tool.completed",
            tool_name: "delegate_legal_researcher",
            call_id: "research-task",
          }, "0-6"),
          sse("custom", {
            type: "task_completed",
            event_type: "subagent.end",
            subagent_type: "legal_researcher",
            task_id: "research-task",
            status: "completed",
          }, "0-7"),
          sse("messages", { delta: "现有工资记录能够" }, "0-8"),
        ].join(""),
      });
      return;
    }
    await route.fulfill({ status: 204 });
  });

  await page.goto("/");
  const originalViewport = page.viewportSize();
  await page.setViewportSize({ width: originalViewport?.width ?? 1280, height: 480 });
  const composerBox = await page.getByLabel("描述案件情况").boundingBox();
  expect(composerBox).not.toBeNull();
  expect((composerBox?.y ?? 0) + (composerBox?.height ?? 0)).toBeLessThanOrEqual(480);
  if (originalViewport) await page.setViewportSize(originalViewport);
  await page.getByRole("button", { name: /档案 0/ }).click();
  await page.getByLabel("案件类型").fill("劳动合同争议");
  await page.getByRole("textbox", { name: "当事人", exact: true }).fill("张某（劳动者）\n某公司");
  await page.getByRole("button", { name: "保存档案" }).click();
  await expect(page.getByRole("button", { name: /档案 3/ })).toBeVisible();

  const materialButton = page.getByRole("button", { name: /材料 0/ });
  if (await materialButton.isVisible()) await materialButton.click();

  await page.getByRole("button", { name: "新建材料" }).click();
  await page.getByPlaceholder("材料名称").fill("工资记录");
  await page.getByPlaceholder("粘贴材料正文").fill("公司连续三个月拖欠工资。");
  await page.getByRole("button", { name: "添加", exact: true }).click();
  const closeMaterials = page.getByRole("button", { name: "关闭材料面板" });
  if (await closeMaterials.isVisible()) await closeMaterials.click();

  await page.getByLabel("描述案件情况").fill("公司拖欠工资怎么办？");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText("现有工资记录能够支持拖欠工资的初步主张")).toBeVisible();
  await expect(page.getByText("[M1:C1]", { exact: true })).toBeVisible();
  await expect(page.getByText("[1]", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("L1234567890abcdef:C30", { exact: true })).toHaveCount(0);
  await expect(page.getByText("未在正文使用的法规", { exact: true })).toHaveCount(0);
  await expect(page.getByText("法律研究 Agent", { exact: true })).toHaveCount(1);
  await expect(page.getByText("检索法规依据", { exact: true })).toHaveCount(1);
  await expect(page.getByText("子任务处理中", { exact: true })).toHaveCount(0);
  await expect(page.getByText("delegate_legal_researcher", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("分析过程").getByText("已完成", { exact: true })).toHaveCount(3);
  await page.reload();
  await expect(page.getByText("法律研究 Agent", { exact: true })).toHaveCount(1);
  await expect(page.getByText("检索法规依据", { exact: true })).toHaveCount(1);
  await expect(page.getByLabel("分析过程").getByText("已完成", { exact: true })).toHaveCount(3);
  await expect(page.getByRole("button", { name: "档案 4，已更新" })).toBeVisible();
  await page.getByRole("button", { name: "档案 4，已更新" }).click();
  await expect(page.getByRole("textbox", { name: "当事人陈述" })).toHaveValue(
    "公司连续三个月拖欠工资",
  );
  await expect(page.getByRole("link", { name: /中华人民共和国劳动合同法/ })).toHaveAttribute(
    "href",
    "https://flk.npc.gov.cn/detail?id=test",
  );
  expect(conversationRequests.filter((item) => item.startsWith("POST "))).toEqual([
    `POST /api/v1/cases/${caseId}/messages/stream`,
  ]);
  expect(resumeRequests).toEqual([{ method: "GET", lastEventId: "0-8" }]);
  expect(conversationRequests.some((item) => item.endsWith("/run"))).toBe(false);
});

function sse(event: string, data: unknown, id?: string): string {
  return `${id ? `id: ${id}\n` : ""}event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}
