import { Button } from "@/components/ui";
import { type User, statuses } from "@/lib/types";
import styles from "./admin-users.module.css";

// 原生表格保留表头关联；小屏按账号排列，长昵称和邮箱可在单元格内换行。
export function UserTable({
  users,
  currentId,
  confirming,
  busy,
  onConfirm,
  onChange,
}: {
  users: User[];
  currentId: string;
  confirming: string | null;
  busy: boolean;
  onConfirm: (id: string | null) => void;
  onChange: (user: User) => void;
}) {
  return (
    <table className={styles.table} role="table">
      <caption className={styles.visuallyHidden}>全站注册账号</caption>
      <thead>
        <tr role="row">
          <th scope="col">用户</th>
          <th scope="col">角色 / 邮箱验证</th>
          <th scope="col">状态</th>
          <th scope="col">操作</th>
        </tr>
      </thead>
      <tbody>
        {users.map((user) => (
          <tr key={user.id} role="row">
            <td data-label="用户" role="cell">
              <strong>{user.displayName}</strong>
              <span className={styles.email}>{user.email}</span>
            </td>
            <td data-label="角色 / 邮箱验证" role="cell">
              <span>{user.role === "ADMIN" ? "管理员" : "普通用户"}</span>
              <small className={styles.verification}>
                {user.emailVerified ? "邮箱已验证" : "邮箱待验证"}
              </small>
            </td>
            <td data-label="状态" role="cell">
              <span className={styles.status}>{statuses[user.status]}</span>
            </td>
            <td data-label="操作" role="cell">
              <div className={styles.rowActions}>
                {user.id === currentId ? (
                  <Button className="secondary" disabled>
                    当前账号
                  </Button>
                ) : confirming === user.id ? (
                  <>
                    <p className={styles.confirmNote}>
                      停用会使该账号的现有登录和客户端授权失效。
                    </p>
                    <Button disabled={busy} onClick={() => onChange(user)}>
                      {busy ? "正在停用…" : "确认停用"}
                    </Button>
                    <Button
                      className="secondary"
                      disabled={busy}
                      onClick={() => onConfirm(null)}
                    >
                      取消
                    </Button>
                  </>
                ) : (
                  <Button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      user.status === "ACTIVE"
                        ? onConfirm(user.id)
                        : onChange(user)
                    }
                  >
                    {user.status === "ACTIVE" ? "停用" : "恢复"}
                  </Button>
                )}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
