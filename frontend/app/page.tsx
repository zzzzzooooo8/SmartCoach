"use client";

import React, { FormEvent, useEffect, useRef, useState } from "react";
import {
  Activity,
  BookOpenText,
  CalendarDays,
  Flame,
  LoaderCircle,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
  Utensils,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const USER_ID = "default";
const CONVERSATION_ID = "main";

type Source = {
  name: string;
  category: string;
  score: number;
  excerpt: string;
};

type ChatMessage = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
};

type Dashboard = {
  intake: number;
  protein: number;
  burn: number;
  target_calories: number | null;
  target_protein: number | null;
  remaining_calories: number | null;
  today_progress: number;
  total_progress: number;
  streak: number;
  cheat_day_left: number | string;
};

type ProfileForm = {
  gender: "male" | "female";
  age: string;
  height_cm: string;
  current_weight_kg: string;
  target_weight_kg: string;
  activity_level: "sedentary" | "light" | "moderate" | "heavy";
  target_loss_speed: string;
  dietary_restrictions: string;
  health_notes: string;
};

const EMPTY_DASHBOARD: Dashboard = {
  intake: 0,
  protein: 0,
  burn: 0,
  target_calories: null,
  target_protein: null,
  remaining_calories: null,
  today_progress: 0,
  total_progress: 0,
  streak: 0,
  cheat_day_left: 6,
};

const EMPTY_PROFILE: ProfileForm = {
  gender: "male",
  age: "",
  height_cm: "",
  current_weight_kg: "",
  target_weight_kg: "",
  activity_level: "sedentary",
  target_loss_speed: "0.5",
  dietary_restrictions: "",
  health_notes: "",
};

const WELCOME: ChatMessage = {
  role: "assistant",
  content: "你好，我是你的减脂教练。完成建档后，我会长期记住计划、记录每天的饮食运动，并基于资料库给你建议。",
};

function splitList(value: string) {
  return value
    .split(/[，,、]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function Onboarding({
  form,
  setForm,
  onSubmit,
  saving,
  error,
}: {
  form: ProfileForm;
  setForm: React.Dispatch<React.SetStateAction<ProfileForm>>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  saving: boolean;
  error: string;
}) {
  const set = (key: keyof ProfileForm, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-[#17372d]/70 p-4 backdrop-blur-md sm:p-8">
      <div className="mx-auto grid min-h-full max-w-5xl items-center">
        <form
          onSubmit={onSubmit}
          className="overflow-hidden rounded-[2rem] border border-white/60 bg-[#f8f5ed] shadow-[0_30px_100px_rgba(15,45,36,.35)]"
        >
          <div className="grid lg:grid-cols-[.8fr_1.2fr]">
            <div className="relative overflow-hidden bg-[#17372d] p-8 text-[#f8f5ed] sm:p-10">
              <div className="absolute -right-20 -top-20 h-56 w-56 rounded-full border border-[#bdd9c9]/20" />
              <div className="absolute -bottom-24 -left-16 h-72 w-72 rounded-full bg-[#c7dfd0]/10" />
              <Sparkles className="mb-8 text-[#c8e3d3]" size={34} />
              <p className="mb-3 text-xs font-semibold tracking-[.28em] text-[#9ec7b2]">FIRST CHECK-IN</p>
              <h1 className="font-editorial text-4xl leading-tight sm:text-5xl">先认识你，<br />再制定计划。</h1>
              <p className="mt-6 max-w-sm text-sm leading-7 text-[#d5e4dc]">
                这些信息会保存在你的本地 SQLite 数据库中，用于计算目标和后续对话。你随时可以更新计划。
              </p>
            </div>

            <div className="p-6 sm:p-10">
              <div className="grid gap-5 sm:grid-cols-2">
                <label className="field-label">
                  性别
                  <select value={form.gender} onChange={(event) => set("gender", event.target.value)} className="field-input">
                    <option value="male">男</option>
                    <option value="female">女</option>
                  </select>
                </label>
                <label className="field-label">
                  年龄
                  <input required type="number" min="16" max="100" value={form.age} onChange={(event) => set("age", event.target.value)} className="field-input" placeholder="例如 28" />
                </label>
                <label className="field-label">
                  身高（厘米）
                  <input required type="number" min="120" max="230" value={form.height_cm} onChange={(event) => set("height_cm", event.target.value)} className="field-input" placeholder="例如 175" />
                </label>
                <label className="field-label">
                  当前体重（千克）
                  <input required type="number" min="30" max="300" step="0.1" value={form.current_weight_kg} onChange={(event) => set("current_weight_kg", event.target.value)} className="field-input" placeholder="例如 78" />
                </label>
                <label className="field-label">
                  目标体重（千克）
                  <input type="number" min="30" max="300" step="0.1" value={form.target_weight_kg} onChange={(event) => set("target_weight_kg", event.target.value)} className="field-input" placeholder="例如 68" />
                </label>
                <label className="field-label">
                  日常活动量
                  <select value={form.activity_level} onChange={(event) => set("activity_level", event.target.value)} className="field-input">
                    <option value="sedentary">久坐办公</option>
                    <option value="light">轻度活动</option>
                    <option value="moderate">中度活动</option>
                    <option value="heavy">重度活动</option>
                  </select>
                </label>
                <label className="field-label">
                  每周目标减重（千克）
                  <select value={form.target_loss_speed} onChange={(event) => set("target_loss_speed", event.target.value)} className="field-input">
                    <option value="0.3">0.3，温和</option>
                    <option value="0.5">0.5，标准</option>
                    <option value="0.7">0.7，较快</option>
                  </select>
                </label>
                <label className="field-label">
                  饮食限制（选填）
                  <input value={form.dietary_restrictions} onChange={(event) => set("dietary_restrictions", event.target.value)} className="field-input" placeholder="用逗号分隔" />
                </label>
                <label className="field-label sm:col-span-2">
                  健康或运动限制（选填）
                  <input value={form.health_notes} onChange={(event) => set("health_notes", event.target.value)} className="field-input" placeholder="例如膝盖旧伤；健康问题请遵医嘱" />
                </label>
              </div>
              {error ? <p className="mt-4 text-sm text-[#a13d31]">{error}</p> : null}
              <button disabled={saving} className="mt-7 flex w-full items-center justify-center gap-2 rounded-2xl bg-[#17372d] px-5 py-4 font-semibold text-white transition hover:bg-[#245744] disabled:opacity-60">
                {saving ? <LoaderCircle className="animate-spin" size={18} /> : <Sparkles size={18} />}
                {saving ? "正在生成计划" : "建立档案并生成计划"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function FitnessAgentPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard>(EMPTY_DASHBOARD);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [profile, setProfile] = useState<ProfileForm>(EMPTY_PROFILE);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const loadBootstrap = async () => {
    const response = await fetch(`${API_BASE}/api/bootstrap?user_id=${USER_ID}&conversation_id=${CONVERSATION_ID}`, { cache: "no-store" });
    if (!response.ok) throw new Error("无法读取后端数据");
    const data = await response.json();
    setNeedsOnboarding(data.needs_onboarding);
    setDashboard({ ...EMPTY_DASHBOARD, ...data.dashboard });
    setMessages(data.messages.length ? data.messages : [WELCOME]);
  };

  useEffect(() => {
    let active = true;
    loadBootstrap()
      .catch(() => {
        if (active) setError("无法连接后端，请确认服务已经启动。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSavingProfile(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/profile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: USER_ID,
          gender: profile.gender,
          age: Number(profile.age),
          height_cm: Number(profile.height_cm),
          current_weight_kg: Number(profile.current_weight_kg),
          target_weight_kg: profile.target_weight_kg ? Number(profile.target_weight_kg) : null,
          activity_level: profile.activity_level,
          target_loss_speed: Number(profile.target_loss_speed),
          dietary_restrictions: splitList(profile.dietary_restrictions),
          health_notes: splitList(profile.health_notes),
        }),
      });
      if (!response.ok) throw new Error("建档信息未通过校验");
      const data = await response.json();
      setDashboard({ ...EMPTY_DASHBOARD, ...data.dashboard });
      setNeedsOnboarding(false);
      setMessages([WELCOME]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "建档失败");
    } finally {
      setSavingProfile(false);
    }
  };

  const sendMessage = async () => {
    const content = input.trim();
    if (!content || sending) return;
    setMessages((current) => [...current, { role: "user", content }]);
    setInput("");
    setSending(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: content, user_id: USER_ID, conversation_id: CONVERSATION_ID }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.reply ?? "处理失败");
      setMessages((current) => [...current, { role: "assistant", content: data.reply, sources: data.sources }]);
      setDashboard({ ...EMPTY_DASHBOARD, ...data.dashboard });
    } catch (cause) {
      setMessages((current) => [...current, { role: "assistant", content: cause instanceof Error ? cause.message : "连接失败，请稍后重试。" }]);
    } finally {
      setSending(false);
    }
  };

  const resetDaily = async () => {
    if (!window.confirm("确认将今天的饮食和运动记录作废吗？")) return;
    const response = await fetch(`${API_BASE}/api/reset/daily`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID }),
    });
    if (response.ok) {
      const data = await response.json();
      setDashboard({ ...EMPTY_DASHBOARD, ...data.dashboard });
    }
  };

  const resetAll = async () => {
    if (!window.confirm("确认清空档案、计划、记录和聊天吗？此操作不可恢复。")) return;
    const response = await fetch(`${API_BASE}/api/reset/all`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID }),
    });
    if (response.ok) {
      setDashboard(EMPTY_DASHBOARD);
      setMessages([WELCOME]);
      setProfile(EMPTY_PROFILE);
      setNeedsOnboarding(true);
    }
  };

  if (loading) {
    return <main className="grid min-h-screen place-items-center bg-[#eef1e9] text-[#17372d]"><LoaderCircle className="animate-spin" size={34} /></main>;
  }

  return (
    <main className="min-h-screen bg-[#eef1e9] text-[#17372d] lg:h-screen lg:overflow-hidden">
      {needsOnboarding ? <Onboarding form={profile} setForm={setProfile} onSubmit={saveProfile} saving={savingProfile} error={error} /> : null}

      <div className="mx-auto grid min-h-screen max-w-[1600px] lg:h-screen lg:grid-cols-[380px_1fr]">
        <aside className="relative overflow-hidden bg-[#17372d] p-6 text-[#f8f5ed] sm:p-8 lg:flex lg:flex-col lg:justify-between">
          <div className="pointer-events-none absolute -right-24 top-20 h-72 w-72 rounded-full border border-[#c8e3d3]/10" />
          <div>
            <div className="mb-8 flex items-center gap-3">
              <div className="grid h-11 w-11 place-items-center rounded-2xl bg-[#c6dfcf] text-[#17372d]"><Activity size={23} /></div>
              <div>
                <p className="font-editorial text-xl">Smart Coach</p>
                <p className="text-[10px] tracking-[.24em] text-[#9ec7b2]">DAILY PRACTICE</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-1">
              <section className="col-span-2 rounded-[1.75rem] bg-[#f8f5ed] p-5 text-[#17372d] lg:col-span-1">
                <div className="mb-2 flex items-end justify-between">
                  <span className="text-xs text-[#557166]">总减脂进度</span>
                  <strong className="font-editorial text-3xl">{dashboard.total_progress}%</strong>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-[#dbe3dc]"><div className="h-full rounded-full bg-[#ce6f45] transition-all" style={{ width: `${dashboard.total_progress}%` }} /></div>
              </section>

              <section className="rounded-[1.5rem] border border-white/10 bg-white/5 p-4">
                <Utensils className="mb-5 text-[#9ec7b2]" size={19} />
                <p className="text-xs text-[#9fb8ad]">今日摄入</p>
                <p className="mt-1 text-xl font-semibold">{dashboard.intake} <small className="text-xs font-normal">kcal</small></p>
                <p className="mt-1 text-[11px] text-[#79998a]">目标 {dashboard.target_calories ?? "--"}</p>
              </section>
              <section className="rounded-[1.5rem] border border-white/10 bg-white/5 p-4">
                <Flame className="mb-5 text-[#e79568]" size={19} />
                <p className="text-xs text-[#9fb8ad]">运动消耗</p>
                <p className="mt-1 text-xl font-semibold">{dashboard.burn} <small className="text-xs font-normal">kcal</small></p>
                <p className="mt-1 text-[11px] text-[#79998a]">达成 {dashboard.today_progress}%</p>
              </section>
              <section className="col-span-2 rounded-[1.5rem] bg-[#c6dfcf] p-5 text-[#17372d] lg:col-span-1">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-[#557166]">放松餐倒计时</p>
                    <p className="font-editorial mt-1 text-2xl">{typeof dashboard.cheat_day_left === "number" ? `还有 ${dashboard.cheat_day_left} 天` : dashboard.cheat_day_left}</p>
                  </div>
                  <CalendarDays className="opacity-40" size={28} />
                </div>
              </section>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-2 gap-3">
            <button onClick={resetDaily} className="control-button"><RotateCcw size={14} />日清空</button>
            <button onClick={resetAll} className="control-button text-[#f2aa93]"><Trash2 size={14} />总清空</button>
          </div>
        </aside>

        <section className="flex min-h-[70vh] flex-col bg-[#f8f5ed] lg:h-screen">
          <header className="flex items-center justify-between border-b border-[#dce2d9] px-5 py-4 sm:px-8">
            <div>
              <p className="font-editorial text-xl">今日对话</p>
              <p className="text-xs text-[#75877e]">档案、记录和记忆均由后端管理</p>
            </div>
            <div className="flex items-center gap-2 rounded-full bg-[#e4ebe4] px-3 py-2 text-xs text-[#466358]"><span className="h-2 w-2 rounded-full bg-[#4e9b72]" />SQLite 已连接</div>
          </header>

          <div ref={scrollRef} className="chat-scroll flex-1 space-y-5 overflow-y-auto px-4 py-6 sm:px-8 sm:py-8">
            {messages.map((message, index) => (
              <article key={message.id ?? `${message.role}-${index}`} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[88%] sm:max-w-[72%] ${message.role === "user" ? "user-bubble" : "assistant-bubble"}`}>
                  <p className="whitespace-pre-wrap leading-7">{message.content}</p>
                  {message.sources?.length ? (
                    <details className="mt-4 border-t border-[#cbd8cf] pt-3 text-xs text-[#5e756a]">
                      <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold"><BookOpenText size={14} />查看本轮资料来源</summary>
                      <div className="mt-3 space-y-2">
                        {message.sources.slice(0, 4).map((source, sourceIndex) => <p key={`${source.name}-${sourceIndex}`}>- {source.name}：{source.excerpt.slice(0, 90)}…</p>)}
                      </div>
                    </details>
                  ) : null}
                </div>
              </article>
            ))}
            {sending ? <div className="flex justify-start"><div className="assistant-bubble flex items-center gap-2 text-sm text-[#6e8278]"><LoaderCircle className="animate-spin" size={16} />正在分析、检索并更新记录…</div></div> : null}
          </div>

          <footer className="border-t border-[#dce2d9] bg-[#f8f5ed]/95 p-4 sm:p-6">
            <div className="mx-auto flex max-w-4xl items-end gap-3 rounded-[1.5rem] border border-[#ccd8cf] bg-white p-2 pl-5 shadow-[0_10px_35px_rgba(33,68,53,.08)]">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    void sendMessage();
                  }
                }}
                rows={1}
                placeholder="告诉教练你吃了什么、做了什么，或直接提问…"
                className="max-h-32 min-h-11 flex-1 resize-none bg-transparent py-3 text-sm outline-none placeholder:text-[#9aaa9f]"
              />
              <button onClick={() => void sendMessage()} disabled={sending || !input.trim()} aria-label="发送消息" className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-[#17372d] text-white transition hover:bg-[#265746] disabled:opacity-40"><Send size={18} /></button>
            </div>
            {error ? <p className="mt-2 text-center text-xs text-[#a13d31]">{error}</p> : null}
          </footer>
        </section>
      </div>
    </main>
  );
}
