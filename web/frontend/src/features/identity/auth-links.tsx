import Link from "next/link";
import { authHref } from "./return-path";
import styles from "./auth.module.css";

// 登录只保留注册入口，邮件帮助在注册成功后出现，避免初次访问面对一排操作。
export function AuthLinks({ mode, destination, complete }: {
  mode: string;
  destination: string;
  complete: boolean;
}) {
  return <>
    {complete ? <Link className={`button-link ${styles.submit}`} href={authHref("/login", destination)}>
      返回登录
    </Link> : <p className={styles.switchAccount}>
      {mode === "login" ? <>
        <span>没有账号？</span><Link href={authHref("/register", destination)}>创建账号</Link>
      </> : <>
        {mode === "register" && <span>已有账号？</span>}
        <Link href={authHref("/login", destination)}>返回登录</Link>
      </>}
    </p>}
    {mode === "register" && complete && <p className={styles.mailHelp}>
      <span>没有收到邮件？</span><Link href={authHref("/verify-email", destination)}>重新发送验证邮件</Link>
    </p>}
  </>;
}
