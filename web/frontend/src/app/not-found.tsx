import { Heading } from "@/components/ui";
import Link from "next/link";
export default function NotFound() {
  return (
    <div className="container">
      <Heading title="这个页面还没有住进来。">
        请检查地址，或返回首页继续。
      </Heading>
      <Link className="button-link" href="/">
        返回首页
      </Link>
    </div>
  );
}
