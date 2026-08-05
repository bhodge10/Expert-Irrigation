export default function Avatar({ user, small = false }) {
  if (!user) return null;
  return (
    <span
      className={small ? "eq-av sm" : "eq-av"}
      style={{ background: user.color }}
      title={user.display_name}
    >
      {user.initials}
    </span>
  );
}
