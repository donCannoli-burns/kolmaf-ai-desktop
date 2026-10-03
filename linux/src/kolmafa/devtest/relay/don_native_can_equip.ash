// Canonical source: Don project src/kolmafa/devtest/relay/don_native_can_equip.ash
// Fixed read-only native query: boolean can_equip(item) for one item_id.
// Exactly one operation. No mutation, no CLI, no arbitrary evaluation,
// no choice handling, no combat, no inventory use, no chat/mail.
//
// The Don transport always requests this helper with exactly:
//   /don_native_can_equip.ash?relay=true&item_id=<positive integer>
// The `relay=true` field is KoLmafia's own fixed relay-script dispatch
// parameter, not a caller-selected operation.

void main() {
  string raw = form_field("item_id");
  if (length(raw) < 1 || length(raw) > 10 || !is_integer(raw)) {
    write("{\"schema\":\"kolmaf-native-can-equip-v1\",\"ok\":false,\"item_id\":0,\"error\":\"INVALID_ITEM_ID\"}");
    return;
  }
  int item_id = to_int(raw);
  if (item_id <= 0) {
    write("{\"schema\":\"kolmaf-native-can-equip-v1\",\"ok\":false,\"item_id\":0,\"error\":\"INVALID_ITEM_ID\"}");
    return;
  }
  item it = to_item(item_id);
  if (it == $item[none]) {
    write("{\"schema\":\"kolmaf-native-can-equip-v1\",\"ok\":false,\"item_id\":" + item_id + ",\"error\":\"UNKNOWN_ITEM\"}");
    return;
  }
  boolean allowed = can_equip(it);
  string allowed_text = "false";
  if (allowed) {
    allowed_text = "true";
  }
  write("{\"schema\":\"kolmaf-native-can-equip-v1\",\"ok\":true,\"item_id\":" + item_id + ",\"item_name\":\"" + to_string(it) + "\",\"can_equip\":" + allowed_text + "}");
}
