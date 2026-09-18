import type { ModelConfiguration } from './agentTypes'

export type ProviderPreset = { id: string; name: string; short: string; protocol: ModelConfiguration['provider']; url: string; docs?: string }
export const modelProviders: ProviderPreset[] = [
  { id: 'local', name: 'Local / offline model', short: 'L', protocol: 'local', url: 'http://127.0.0.1:8001/v1' },
  { id: 'openai', name: 'OpenAI', short: 'O', protocol: 'openai', url: 'https://api.openai.com/v1', docs: 'https://platform.openai.com/docs/models' },
  { id: 'deepseek', name: 'DeepSeek', short: 'D', protocol: 'openai_compatible', url: 'https://api.deepseek.com', docs: 'https://api-docs.deepseek.com' },
  { id: 'qwen', name: 'Qwen · China', short: 'Q', protocol: 'openai_compatible', url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', docs: 'https://help.aliyun.com/en/model-studio/base-url' },
  { id: 'qwen-intl', name: 'Qwen · International', short: 'Q', protocol: 'openai_compatible', url: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', docs: 'https://help.aliyun.com/en/model-studio/base-url' },
  { id: 'moonshot', name: 'Kimi · China', short: 'K', protocol: 'openai_compatible', url: 'https://api.moonshot.cn/v1', docs: 'https://platform.moonshot.cn/docs' },
  { id: 'moonshot-intl', name: 'Kimi · International', short: 'K', protocol: 'openai_compatible', url: 'https://api.moonshot.ai/v1', docs: 'https://platform.moonshot.ai/docs' },
  { id: 'siliconflow', name: 'SiliconFlow', short: 'S', protocol: 'openai_compatible', url: 'https://api.siliconflow.cn/v1', docs: 'https://docs.siliconflow.cn/docs/userguide/quickstart' },
  { id: 'openrouter', name: 'OpenRouter', short: 'R', protocol: 'openai_compatible', url: 'https://openrouter.ai/api/v1', docs: 'https://openrouter.ai/docs/quickstart' },
  { id: 'gemini', name: 'Google Gemini', short: 'G', protocol: 'openai_compatible', url: 'https://generativelanguage.googleapis.com/v1beta/openai', docs: 'https://ai.google.dev/gemini-api/docs/openai' },
  { id: 'anthropic', name: 'Anthropic · Claude', short: 'A', protocol: 'anthropic', url: 'https://api.anthropic.com/v1', docs: 'https://platform.claude.com/docs/en/api/messages/create' },
]

export function findModelProvider(url: string) {
  const address = url.replace(/\/$/, '')
  return modelProviders.find((item) => item.id !== 'local' && (item.url === address || (item.id === 'deepseek' && address === 'https://api.deepseek.com/v1')))
}
