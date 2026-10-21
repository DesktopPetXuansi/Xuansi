import { Heading } from "@/components/ui";
import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";
import { helpTopics, type HelpTopic } from "./content";
import { questions } from "./questions";
import styles from "./help.module.css";

function QuestionList({ compact = false }: { compact?: boolean }) {
  return (
    <div className={styles.questions}>
      {(compact ? questions.slice(0, 3) : questions).map((item) => (
        <details key={item.question}>
          <summary>{item.question}</summary>
          <div>
            <p>{item.answer}</p>
            <Link className="quiet-link" href={item.href}>
              {item.label} <ArrowRight size={15} aria-hidden />
            </Link>
          </div>
        </details>
      ))}
    </div>
  );
}

function FeedbackLink() {
  return (
    <div className={styles.feedback}>
      <div>
        <h2>还没有解决？</h2>
        <p>带上版本、操作步骤和报错信息，方便我们找到原因。</p>
      </div>
      <Link className="quiet-link" href="/#feedback">
        写下反馈 <ArrowRight size={15} aria-hidden />
      </Link>
    </div>
  );
}

// 指南和问答全部服务端渲染；原生 details 保持键盘可用且无需额外脚本。
export function HelpCenter() {
  return (
    <div className={`container ${styles.center}`}>
      <Heading eyebrow="使用帮助" title="你想先做什么？">
        安装、聊天、换形象。从正在做的事情开始找，不用先读一整本文档。
      </Heading>
      <section className={styles.start} aria-labelledby="start-title">
        <div>
          <p className="eyebrow">刚认识玄司</p>
          <h2 id="start-title">第一次用？从这里开始。</h2>
          <p>下载安装 → 选择 AI 聊天方式 → 打开桌宠，发出第一句话。</p>
        </div>
        <Link className="button-link" href="/docs/getting-started">
          查看新手步骤 <ArrowRight size={16} aria-hidden />
        </Link>
      </section>
      <section className={styles.topics} aria-label="按操作查找帮助">
        {helpTopics.slice(1).map((topic) => (
          <Link key={topic.slug} href={`/docs/${topic.slug}`}>
            <div>
              <h2>{topic.title}</h2>
              <p>{topic.summary}</p>
            </div>
            <ArrowRight size={20} aria-hidden />
          </Link>
        ))}
      </section>
      <section className={styles.faq} aria-labelledby="quick-questions">
        <div className={styles.sectionHeading}>
          <h2 id="quick-questions">大家常问</h2>
          <Link className="quiet-link" href="/faq">
            查看全部问题 <ArrowRight size={15} aria-hidden />
          </Link>
        </div>
        <QuestionList compact />
      </section>
      <FeedbackLink />
    </div>
  );
}

export function HelpArticle({ topic }: { topic: HelpTopic }) {
  return (
    <div className={`container ${styles.article}`}>
      <Link className="quiet-link" href="/docs">
        <ArrowLeft size={15} aria-hidden /> 返回使用帮助
      </Link>
      <Heading eyebrow="使用帮助" title={topic.title}>
        {topic.summary}
      </Heading>
      <div className={styles.articleLayout}>
        <article>
          <ol className={styles.steps}>
            {topic.steps.map((step, index) => (
              <li key={step.title} id={`step-${index + 1}`}>
                <span className={styles.stepNumber} aria-hidden>
                  {index + 1}
                </span>
                <div>
                  <h2>{step.title}</h2>
                  <p>{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
          <p className={styles.note}>{topic.note}</p>
        </article>
        <aside className={styles.aside}>
          <nav aria-label="本页步骤">
            <h2>在这篇里</h2>
            {topic.steps.map((step, index) => (
              <a key={step.title} href={`#step-${index + 1}`}>
                {index + 1}. {step.title}
              </a>
            ))}
          </nav>
          <nav aria-label="相关帮助">
            <h2>接下来</h2>
            {topic.related.map((link) => (
              <Link key={link.href} href={link.href}>
                {link.label} →
              </Link>
            ))}
          </nav>
        </aside>
      </div>
      <FeedbackLink />
    </div>
  );
}

export function HelpQuestions() {
  return (
    <div className={`container ${styles.questionPage}`}>
      <Link className="quiet-link" href="/docs">
        <ArrowLeft size={15} aria-hidden /> 返回使用帮助
      </Link>
      <Heading eyebrow="使用帮助 / 常见问题" title="这些问题，你可能也想问。">
        需要完整操作步骤，可以回到使用帮助，按正在做的事情查找。
      </Heading>
      <QuestionList />
      <FeedbackLink />
    </div>
  );
}
