import Image from "next/image";
import Link from "next/link";
export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">MEET XUANSI / 遇见玄司</p>
          <h1>
            把陪伴，
            <br />
            留在你的<em>桌面。</em>
          </h1>
          <p>
            她会听你说话，也会看看你正在忙什么。
            <br />
            一个住在电脑里的 AI 伙伴，让日常多一点回应。
            <br />
            推理在本地运行，陪伴由你决定。
          </p>
          <div className="actions">
            <Link className="button-link" href="/download">
              下载 Windows 客户端 <span aria-hidden>↓</span>
            </Link>
            <Link href="/features" className="quiet-link">
              认识玄司 ↗
            </Link>
          </div>
          <p className="hero-note">
            当前版本 0.5.6 · Windows 11 x64 · NVIDIA / CUDA 12.4
            <br />
            首次安装需要联网，安装路径需要 D 盘。
          </p>
        </div>
        <div className="hero-art">
          <span className="art-label">玄司 / YOUR DESKTOP COMPANION</span>
          <Image
            src="/brand/front.png"
            alt="玄司角色：黑金服饰与长发的桌面伙伴"
            fill
            priority
            sizes="(max-width:640px) 100vw, 50vw"
          />
          <span className="art-bottom">XUANSI — 在场，而不打扰。</span>
        </div>
      </section>
      <div className="principles">
        <div>
          <span>01</span>
          <section>
            <h3>运行在你的设备</h3>
            <p>本地模型推理，保留自己的数据边界。</p>
          </section>
        </div>
        <div>
          <span>02</span>
          <section>
            <h3>按你的节奏陪伴</h3>
            <p>聊天、语音、观察与休眠，由你开启。</p>
          </section>
        </div>
        <div>
          <span>03</span>
          <section>
            <h3>让形象属于你</h3>
            <p>管理模型、动作、表情与透明动图。</p>
          </section>
        </div>
      </div>
      <div className="container">
        <section className="home-section">
          <div className="section-top">
            <div>
              <p className="eyebrow">SMALL MOMENTS / 日常之间</p>
              <h2>不只是桌面上的一个身影。</h2>
            </div>
            <Link className="quiet-link" href="/features">
              查看全部功能 ↗
            </Link>
          </div>
          <div className="feature-list">
            <article>
              <span className="feature-number">01 / 对话</span>
              <h3>想到什么，就聊什么。</h3>
              <p>
                文字交流与连续语音，在工作间隙分享想法。语音功能需要相应模型与设备支持。
              </p>
            </article>
            <article>
              <span className="feature-number">02 / 观察</span>
              <h3>一起看看你的屏幕。</h3>
              <p>
                在你开启后，玄司可以观察屏幕内容并回应。截图参与本地推理，是否开启由你掌握。
              </p>
            </article>
            <article>
              <span className="feature-number">03 / 记忆</span>
              <h3>记住你愿意留下的事。</h3>
              <p>
                明确授权的长期记忆，保存在本地。你可以检查与管理，而不是默认上传聊天记录。
              </p>
            </article>
          </div>
        </section>
        <section className="library-promo">
          <div>
            <p className="eyebrow">YOUR CHARACTERS / 你的形象</p>
            <h2>
              一个资源库，
              <br />
              管理每一种陪伴的可能。
            </h2>
            <p>
              为模型保留作者和许可，为动作标注精确依赖。上传默认私有，通过校验后再交给接入版客户端试载。
            </p>
            <Link className="button-link secondary" href="/resources">
              探索资源库 ↗
            </Link>
          </div>
          <div className="library-types">
            <div>
              <span>Live2D 模型</span>
              <span>完整导出包</span>
            </div>
            <div>
              <span>动作 / 表情</span>
              <span>绑定模型版本</span>
            </div>
            <div>
              <span>图片 / 透明动图</span>
              <span>你的桌面形象</span>
            </div>
            <p className="legal-note">
              资源平台需要客户端接入版。0.5.6 仍使用原有本地导入流程。
            </p>
          </div>
        </section>
      </div>
    </>
  );
}
