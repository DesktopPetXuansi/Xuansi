import Link from "next/link";
import { authHref } from "./return-path";
import styles from "./auth.module.css";

// 注册与登录互相保留入口，完成密码重置或旧邮件验证后返回登录。
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

  </>;
}
