import type { ReactNode } from "react";
import { Drawer } from "antd";
import { CloseOutlined } from "@ant-design/icons";

export default function LandingDrawer({ title, children, onClose }: { title: ReactNode; children: ReactNode; onClose: () => void }) {
  return <Drawer title={title} open onClose={onClose} closeIcon={<CloseOutlined aria-hidden="true" />} size={300} className="landing-mobile-drawer">{children}</Drawer>;
}
