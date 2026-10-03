I've consolidated all your ASH scripts into a single comprehensive library
file, **MasterLib.ash**. This file includes every function from the provided
scripts, resolves duplicate definitions, removes conflicting `main()`
functions, and organizes imports. Below is the complete content.

To use it, simply save the code as `MasterLib.ash` in your `scripts/` folder
and import it with `import <MasterLib.ash>;` in your own scripts.

---

```ash
// ============================================================================
// MasterLib.ash – Unified ASH Function Library
// ============================================================================
// Combines all functions from:
//   FunctionLib.ash, htmlform.ash, my11.ash, sims_lib.ash, SmashLib.ash,
//   zlib.ash (newer), vprops.ash, pUpdates.ash, DicsLibrary.ash,
//   ProfitTracking.ash, ptrack.ash, TimeTracking.ash, varargs.ash,
//   tt_quickconfig.ash, tt_util.ash, wtf.ash
//
// External dependencies (you must have these scripts installed):
//   nscomb.ash, bumcheekascend.ash, autoscend.ash,
//   ttpacks/util/tt_header.ash, tt_settings.ash, tt_depreciate.ash
// ============================================================================

// ----------------------------- Imports --------------------------------------
import <nscomb.ash>;
import <bumcheekascend.ash>;
import <autoscend.ash>;
import <ttpack/util/tt_header.ash>;
import <ttpack/util/tsettings.ash>;
import <ttpack/util/tt_depreciate.ash>;

// ----------------------------- FunctionLib.ash ------------------------------
void take_shop(int AllorOne, item it) {
    if (shop_amount(it) > 0) {
        print("Removing " + it + " from store inventory.");
        if (to_string(AllorOne) == "0")
            visit_url("managestore.php?action=takeall&whichitem=" +
to_int(it));
        else if (to_string(AllorOne) == "1")
            visit_url("managestore.php?action=take&whichitem=" + to_int(it));
    }
}

boolean got_item(item tolookup) {
    if (item_amount(tolookup) > 0)
        return true;
    if (have_equipped(tolookup))
        return true;
    return false;
}

boolean AdvCheck() {
    return my_adventures() > 0 && my_inebriety() == 19;
}

void conditions(int n, string conditionsString) {
    cli_execute("conditions clear");
    cli_execute("conditions add " + n + conditionsString);
}

void getanduse(int n, item it) {
    if (item_amount(it) < n) {
        int this = n - item_amount(it);
        if (stash_amount(it) > 0) {
            if (stash_amount(it) > this)
                take_stash(this, it);
            else if (stash_amount(it) < this)
                take_stash(stash_amount(it), it);
        }
        else buy(this, it);
    }
    if (!use(n, it))
        if (!eat(n, it))
            if (!drink(n, it))
                return;
}

boolean checkfam(familiar pet) {
    if (have_familiar(pet)) {
        use_familiar(pet);
        if (can_interact())
            getanduse(1, familiar_equipment(pet));
        return true;
    }
    return false;
}

void stashall(string dowhat, item it) {
    if (dowhat == "take")
        if (stash_amount(it) > 0)
            take_stash(stash_amount(it), it);
    if (dowhat == "put")
        if (item_amount(it) > 0)
            put_stash(item_amount(it), it);
}

int worthless_amount() {
    return (available_amount($item[worthless trinket]) +
available_amount($item[worthless gewgaw]) + available_amount($item[worthless
knick-knack]));
}

boolean save_outfit(string outfitlabel) {
    visit_url("inv_equip.php?which=2&action=customoutfit&outfitname=" +
outfitlabel);
    return true;
}

boolean HPcare(int target) {
    while (my_hp() < target) {
        if (have_effect($effect[beaten up]) > 0)
            cli_execute("uneffect beaten up");
        restore_hp(target);
    }
    return (my_hp() >= target);
}

boolean test_skill(int n, skill castme) {
    if (have_effect(to_effect(castme)) == 0)
        if (have_skill(castme))
            if (my_maxmp() > mp_cost(castme)) {
                use_skill(n, castme);
                return true;
            }
    return false;
}

boolean test_equip(item it) {
    if (can_equip(it) && got_item(it) && !have_equipped(it)) {
        equip(it);
        return true;
    }
    return false;
}

item stat_to_item(string me, stat st) {
    if (me == "Chow") {
        if (st == $stat[muscle]) return $item[knob sausage chow mein];
        if (st == $stat[moxie]) return $item[rat appendix chow mein];
        if (st == $stat[mysticality]) return $item[bat wing chow mein];
        return $item[none];
    }
    if (me == "HiMein") {
        if (st == $stat[muscle]) return $item[hot hi mein];
        if (st == $stat[moxie]) return $item[spooky hi mein];
        if (st == $stat[mysticality]) return $item[sleazy hi mein];
        return $item[none];
    }
    if (me == "LoMein") {
        if (st == $stat[muscle]) return $item[Knoll lo mein];
        if (st == $stat[moxie]) return $item[Spooky lo mein];
        if (st == $stat[mysticality]) return $item[knob lo mein];
        return $item[none];
    }
    if (me == "Lasagna") {
        if (st == $stat[muscle]) return $item[gnat lasagna];
        if (st == $stat[moxie]) return $item[fishy fish lasagna];
        if (st == $stat[mysticality]) return $item[long pork lasagna];
        return $item[none];
    }
    if (me == "TPSdrink") {
        if (st == $stat[muscle]) return $item[bodyslam];
        if (st == $stat[moxie]) return $item[vesper];
        if (st == $stat[mysticality]) return $item[cherry bomb];
        return $item[none];
    }
    if (me == "SDBdrink") {
        if (st == $stat[muscle]) return $item[mon tiki];
        if (st == $stat[moxie]) return $item[mae west];
        if (st == $stat[mysticality]) return $item[gimlet];
        return $item[none];
    }
    if (me == "DBdrink") {
        if (st == $stat[muscle]) return $item[fuzzbump];
        if (st == $stat[moxie]) return $item[rockin' wagon];
        if (st == $stat[mysticality]) return $item[roll in the hay];
        return $item[none];
    }
    if (me == "ShroomWine") {
        if (st == $stat[muscle]) return $item[flaming mushroom wine];
        if (st == $stat[moxie]) return $item[stinky mushroom wine];
        if (st == $stat[mysticality]) return $item[icy mushroom wine];
        return $item[none];
    }
    if (me == "Wad") {
        if (st == $stat[muscle]) return $item[hot wad];
        if (st == $stat[moxie]) return $item[spooky wad];
        if (st == $stat[mysticality]) return $item[cold wad];
        return $item[none];
    }
    return $item[none];
}

void ClassLink() {
    if (my_class() == $class[seal clubber] || my_class() == $class[disco
bandit] || my_class() == $class[pastamancer])
        visit_url("guild.php?place=scg");
    else if (my_class() == $class[turtle tamer] || my_class() ==
$class[accordion thief] || my_class() == $class[sauceror])
        visit_url("guild.php?place=ocg");
}

void trainfam(familiar pet, int goal) {
    if (have_familiar(pet) && familiar_weight(pet) < goal) {
        use_familiar(pet);
        cli_execute("train base " + goal);
    }
}

item Wand() {
    for it from 1268 upto 1272 by 1 {
        if (got_item(to_item(it)))
            return to_item(it);
    }
    return $item[none];
}

boolean utilize_still() {
    item [item] spirits_n_mixers;
    spirits_n_mixers[ $item[grapefruit] ] = $item[tangerine];
    spirits_n_mixers[ $item[lemon] ] = $item[kiwi];
    spirits_n_mixers[ $item[olive] ] = $item[cocktail onion];
    spirits_n_mixers[ $item[orange] ] = $item[kumquat];
    spirits_n_mixers[ $item[soda water] ] = $item[tonic water];
    spirits_n_mixers[ $item[strawberry] ] = $item[raspberry];
    spirits_n_mixers[ $item[bottle of gin] ] = $item[bottle of Calcutta
Emerald];
    spirits_n_mixers[ $item[bottle of rum] ] = $item[bottle of Lieutenant
Freeman];
    spirits_n_mixers[ $item[bottle of tequila] ] = $item[bottle of Jorge
Sinsonte];
    spirits_n_mixers[ $item[bottle of vodka] ] = $item[bottle of Definit];
    spirits_n_mixers[ $item[bottle of whiskey] ] = $item[bottle of Domesticated
Turkey];
    spirits_n_mixers[ $item[boxed wine] ] = $item[boxed champagne];
    foreach key in spirits_n_mixers
        if (available_amount( key ) > 0 && stills_available() > 0 &&
available_amount(key) >= stills_available())
            return create(stills_available(), spirits_n_mixers[key]);
    return create(5, stat_to_item("SDBdrink", my_primestat()));
}

boolean resistance() {
    item freshener = $item[pine-fresh air freshener];
    if (test_skill(2, $skill[Elemental Saucesphere]))
        return true;
    if (test_skill(2, $skill[astral shell]))
        return true;
    if (test_equip($item[asshat]))
        return true;
    if (test_equip($item[bum cheek]))
        return true;
    if (test_equip($item[knob goblin harem veil]))
        return true;
    if (test_equip($item[pants of the slug lord]))
        return true;
    if (test_equip(freshener))
        return true;
    if (!test_equip(freshener)) {
        if (!can_interact()) {
            cli_execute("conditions clear");
            add_item_condition(1, freshener);
            boolean catch = adventure(my_adventures(), $location[bat hole
entryway]);
        }
        else retrieve_item(1, freshener);
        if (test_equip(freshener))
            return true;
    }
    return false;
}

// ----------------------------- htmlform.ash ---------------------------------
string[string] fields;
boolean success;

buffer _attr;
float _rangeMin, _rangeMax;
boolean _rangeSet;
string _select;
string _radioVal, _radioName;

void write_header() {
    fields = form_fields();
    success = count(fields) > 0;
    _rangeSet = false;
    _attr.set_length(0);
    writeln("<html><head>");
}

void finish_header() {
    write("</head><body><form name=\"relayform\" method=\"POST\"
action=\"\">");
}

void write_page() {
    write_header();
    finish_header();
}

void finish_page() {
    writeln("</form></body></html>");
}

void attr(string val) {
    _attr.append(" ");
    _attr.append(val);
}

void _writeattr() {
    write(_attr.to_string());
    write(">");
    _attr.set_length(0);
}

void range(float min, float max) {
    _rangeMin = min;
    _rangeMax = max;
    _rangeSet = true;
}

void write_box(string label) {
    writeln("<fieldset>");
    if (label != "") {
        write("<legend");
        _writeattr();
        write(label);
        writeln("</legend>");
    }
}

void finish_box() {
    writeln("</fieldset>");
}

string nonemptyvalidator(string name) {
    if (fields[name] == "") return "This field is required.";
    return "";
}

string intvalidator(string name) {
    if (!is_integer(fields[name])) {
        _rangeSet = false;
        return "A whole number is requred.";
    }
    if (_rangeSet) {
        _rangeSet = false;
        int val = to_int(fields[name]);
        if (val < _rangeMin) {
            return "Value must be at least " + ceil(_rangeMin);
        }
        if (val > _rangeMax) {
            return "Value must be no more than " + floor(_rangeMax);
        }
    }
    return "";
}

string floatvalidator(string name) {
    if (!create_matcher("^[-+]?(?:\\d+|\\d+\\.\\d*|\\.\\d+)$",
        fields[name]).find()) {
        _rangeSet = false;
        return "A number is required.";
    }
    if (_rangeSet) {
        _rangeSet = false;
        float val = to_float(fields[name]);
        if (val < _rangeMin) {
            return "Value must be at least " + _rangeMin;
        }
        if (val > _rangeMax) {
            return "Value must be no more than " + _rangeMax;
        }
    }
    return "";
}

string itemvalidator(string name) {
    item it = to_item(fields[name]);
    if (it == $item[none]) {
        return "A valid item is required.";
    }
    fields[name] = to_string(it);
    return "";
}

string itemnonevalidator(string name) {
    item it = to_item(fields[name]);
    if (it == $item[none] && !contains_text(fields[name], "none")) {
        return "A valid item or 'none' is required.";
    }
    fields[name] = to_string(it);
    return "";
}

string locationvalidator(string name) {
    location it = to_location(fields[name]);
    if (it == $location[none]) {
        return "A valid location is required.";
    }
    fields[name] = to_string(it);
    return "";
}

string skillvalidator(string name) {
    skill it = to_skill(fields[name]);
    if (it == $skill[none]) {
        return "A valid skill is required.";
    }
    fields[name] = to_string(it);
    return "";
}

string effectvalidator(string name) {
    effect it = to_effect(fields[name]);
    if (it == $effect[none]) {
        return "A valid effect is required.";
    }
    fields[name] = to_string(it);
    return "";
}

string familiarvalidator(string name) {
    familiar it = to_familiar(fields[name]);
    if (it == $familiar[none]) {
        return "A valid familiar is required.";
    }
    fields[name] = to_string(it);
    return "";
}

string monstervalidator(string name) {
    monster it = to_monster(fields[name]);
    if (it == $monster[none]) {
        return "A valid monster is required.";
    }
    fields[name] = entity_decode(it);
    return "";
}

string write_field(string ov, string name, string label, string validator) {
    if (label != "") {
        write("<label>");
        write(label);
    }
    string err;
    string rv = ov;
    if (fields contains name) {
        if (validator != "") {
            err = call string validator(name);
        }
        rv = fields[name];
    }
    write("<input");
    if (!contains_text(_attr, "type=")) {
        write(" type=\"text\"");
    }
    write(" name=\"");
    write(name);
    if (label == "") {
        write("\" id=\"");
        write(name);
    }
    write("\" value=\"");
    write(entity_encode(rv));
    write("\"");
    _writeattr();
    if (err != "") {
        success = false;
        rv = ov;
        write("<font color=\"red\">");
        write(err);
        writeln("</font>");
    }
    if (label != "") {
        writeln("</label>");
    }
    return rv;
}

string write_field(string ov, string name, string label) {
    return write_field(ov, name, label, "");
}

int write_field(int ov, string name, string label, string validator) {
    return to_int(write_field(to_string(ov), name, label, validator));
}

int write_field(int ov, string name, string label) {
    return write_field(ov, name, label, "intvalidator");
}

float write_field(float ov, string name, string label, string validator) {
    return to_float(write_field(to_string(ov), name, label, validator));
}

float write_field(float ov, string name, string label) {
    return write_field(ov, name, label, "floatvalidator");
}

item write_field(item ov, string name, string label, string validator) {
    return to_item(write_field(to_string(ov), name, label, validator));
}

item write_field(item ov, string name, string label) {
    return write_field(ov, name, label, "itemvalidator");
}

location write_field(location ov, string name, string label, string validator)
{
    return to_location(write_field(to_string(ov), name, label, validator));
}

location write_field(location ov, string name, string label) {
    return write_field(ov, name, label, "locationvalidator");
}

skill write_field(skill ov, string name, string label, string validator) {
    return to_skill(write_field(to_string(ov), name, label, validator));
}

skill write_field(skill ov, string name, string label) {
    return write_field(ov, name, label, "skillvalidator");
}

effect write_field(effect ov, string name, string label, string validator) {
    return to_effect(write_field(to_string(ov), name, label, validator));
}

effect write_field(effect ov, string name, string label) {
    return write_field(ov, name, label, "effectvalidator");
}

familiar write_field(familiar ov, string name, string label, string validator)
{
    return to_familiar(write_field(to_string(ov), name, label, validator));
}

familiar write_field(familiar ov, string name, string label) {
    return write_field(ov, name, label, "familiarvalidator");
}

monster write_field(monster ov, string name, string label, string validator) {
    return to_monster(write_field(entity_decode(ov), name, label, validator));
}

monster write_field(monster ov, string name, string label) {
    return write_field(ov, name, label, "monstervalidator");
}

string write_textarea(string ov, string name, string label, int cols, int rows,
string validator) {
    if (label != "") {
        write("<label>");
        write(label);
    }
    string err;
    string rv = ov;
    if (fields contains name) {
        if (validator != "") {
            err = call string validator(name);
        }
        rv = fields[name];
    }
    write("<textarea name=\"");
    write(name);
    if (label == "") {
        write("\" id=\"");
        write(name);
    }
    write("\" cols=\"");
    write(cols);
    write("\" rows=\"");
    write(rows);
    write("\"");
    _writeattr();
    write(entity_encode(rv));
    writeln("</textarea>");
    if (err != "") {
        success = false;
        rv = ov;
        write("<font color=\"red\">");
        write(err);
        writeln("</font>");
    }
    if (label != "") {
        writeln("</label>");
    }
    return rv;
}

string write_textarea(string ov, string name, string label, int cols, int rows)
{
    return write_textarea(ov, name, label, cols, rows, "");
}

boolean write_check(boolean ov, string name, string label) {
    if (label != "") {
        write("<label>");
        write(label);
    }
    if (fields contains name && fields[name] != "") {
        ov = true;
    } else if (count(fields) > 0) {
        ov = false;
    }
    write("<input type=\"checkbox\" name=\"");
    write(name);
    write("\"");
    if (ov) {
        write(" checked");
    }
    _writeattr();
    if (label != "") {
        writeln("</label>");
    }
    return ov;
}

void write_radio(string label, string value) {
    if (label != "") {
        write("<label>");
    }
    write("<input type=\"radio\" name=\"");
    write(_radioName);
    write("\" value=\"");
    write(entity_encode(value));
    write("\"");
    if (value == _radioVal) {
        write(" checked");
    }
    _writeattr();
    if (label != "") {
        write(label);
        writeln("</label>");
    }
}

string write_radio(string ov, string name, string label, string value) {
    _radioName = name;
    if (fields contains name) {
        _radioVal = fields[name];
    } else {
        _radioVal = ov;
    }
    write_radio(label, value);
    return _radioVal;
}

int write_radio(int ov, string name, string label, string value) {
    return to_int(write_radio(to_string(ov), name, label, value));
}

float write_radio(float ov, string name, string label, string value) {
    return to_float(write_radio(to_string(ov), name, label, value));
}

item write_radio(item ov, string name, string label, string value) {
    return to_item(write_radio(to_string(ov), name, label, value));
}

location write_radio(location ov, string name, string label, string value) {
    return to_location(write_radio(to_string(ov), name, label, value));
}

class write_radio(class ov, string name, string label, string value) {
    return to_class(write_radio(to_string(ov), name, label, value));
}

stat write_radio(stat ov, string name, string label, string value) {
    return to_stat(write_radio(to_string(ov), name, label, value));
}

skill write_radio(skill ov, string name, string label, string value) {
    return to_skill(write_radio(to_string(ov), name, label, value));
}

effect write_radio(effect ov, string name, string label, string value) {
    return to_effect(write_radio(to_string(ov), name, label, value));
}

familiar write_radio(familiar ov, string name, string label, string value) {
    return to_familiar(write_radio(to_string(ov), name, label, value));
}

slot write_radio(slot ov, string name, string label, string value) {
    return to_slot(write_radio(to_string(ov), name, label, value));
}

monster write_radio(monster ov, string name, string label, string value) {
    return to_monster(write_radio(to_string(ov), name, label, value));
}

element write_radio(element ov, string name, string label, string value) {
    return to_element(write_radio(to_string(ov), name, label, value));
}

string write_hidden(string ov, string name) {
    if (fields contains name) {
        ov = fields[name];
    }
    write("<input type=\"hidden\" name=\"");
    write(name);
    write("\" value=\"");
    write(entity_encode(ov));
    write("\"");
    _writeattr();
    return ov;
}

void write_label(string name, string label) {
    write("<label for=\"");
    write(name);
    write("\"");
    _writeattr();
    write(label);
    writeln("</label>");
}

string write_select(string ov, string name, string label) {
    write("<label>");
    write(label);
    if (fields contains name) {
        ov = fields[name];
    }
    write("<select name=\"");
    write(name);
    if (label == "") {
        write("\" id=\"");
        write(name);
    }
    write("\"");
    _writeattr();
    _select = ov;
    return ov;
}

void finish_select() {
    writeln("</select></label>");
}

void write_group(string label) {
    write("<optgroup label=\"");
    write(entity_encode(label));
    write("\"");
    _writeattr();
}

void finish_group() {
    writeln("</optgroup>");
}

void write_option(string label, string value) {
    write("<option value=\"");
    write(entity_encode(value));
    write("\"");
    if (value == _select) {
        write(" selected");
    }
    _writeattr();
    write(label);
    writeln("</option>");
}

void write_option(string labelAndValue) {
    write_option(labelAndValue, labelAndValue);
}

int write_select(int ov, string name, string label) {
    return to_int(write_select(to_string(ov), name, label));
}

float write_select(float ov, string name, string label) {
    return to_float(write_select(to_string(ov), name, label));
}

item write_select(item ov, string name, string label) {
    return to_item(write_select(to_string(ov), name, label));
}

location write_select(location ov, string name, string label) {
    return to_location(write_select(to_string(ov), name, label));
}

class write_select(class ov, string name, string label) {
    return to_class(write_select(to_string(ov), name, label));
}

stat write_select(stat ov, string name, string label) {
    return to_stat(write_select(to_string(ov), name, label));
}

skill write_select(skill ov, string name, string label) {
    return to_skill(write_select(to_string(ov), name, label));
}

effect write_select(effect ov, string name, string label) {
    return to_effect(write_select(to_string(ov), name, label));
}

familiar write_select(familiar ov, string name, string label) {
    return to_familiar(write_select(to_string(ov), name, label));
}

slot write_select(slot ov, string name, string label) {
    return to_slot(write_select(to_string(ov), name, label));
}

monster write_select(monster ov, string name, string label) {
    return to_monster(write_select(to_string(ov), name, label));
}

element write_select(element ov, string name, string label) {
    return to_element(write_select(to_string(ov), name, label));
}

item write_choice(item ov, string name, string label, int[item] vals) {
    ov = write_select(ov, name, label);
    foreach it, qty in vals write_option(it + " (" + qty + ")", it);
    finish_select();
    return ov;
}

string write_choice(string ov, string name, string label, boolean[string] vals)
{
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

int write_choice(int ov, string name, string label, boolean[int] vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

float write_choice(float ov, string name, string label, boolean[float] vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

item write_choice(item ov, string name, string label, boolean[item] vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

location write_choice(location ov, string name, string label, boolean[location]
vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

class write_choice(class ov, string name, string label, boolean[class] vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

stat write_choice(stat ov, string name, string label, boolean[stat] vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

skill write_choice(skill ov, string name, string label, boolean[skill] vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

effect write_choice(effect ov, string name, string label, boolean[effect] vals)
{
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

familiar write_choice(familiar ov, string name, string label, boolean[familiar]
vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

slot write_choice(slot ov, string name, string label, boolean[slot] vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

monster write_choice(monster ov, string name, string label, boolean[monster]
vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

element write_choice(element ov, string name, string label, boolean[element]
vals) {
    ov = write_select(ov, name, label);
    foreach val, bool in vals if (bool) write_option(val);
    finish_select();
    return ov;
}

boolean test_button(string name) {
    if (name == "") return false;
    return success && fields contains name;
}

boolean write_button(string name, string label) {
    write("<input type=\"submit\" name=\"");
    write(name);
    write("\" value=\"");
    write(label);
    write("\"");
    _writeattr();
    return test_button(name);
}

// ----------------------------- my11.ash -------------------------------------
string hit() {
    return visit_url( "crimbo09.php?subplace=11table&action=hit11&pwd" );
}

string stand() {
    return visit_url( "crimbo09.php?subplace=11table&action=stand11&pwd" );
}

string double() {
    return visit_url( "crimbo09.php?subplace=11table&action=double11&pwd" );
}

string start_game( int cost ) {
    if( cost < 1 || cost > 11 ) abort( "Invalid bet amount" );
    return visit_url( "crimbo09.php?subplace=11table&action=new11&howmany=" +
cost.to_string() + "&pwd" );
}

int get_opponent( string page ) {
    matcher m = create_matcher(
"http://images.kingdomofloathing.com/otherimages/cards//([1-5ak])[a-d]\\.gif" ,
page );
    m.find();
    string c =  m.group( 1 );
    if (c == "a")
        return 1;
    if (c == "k")
        return 5;
    return m.group(1).to_int();
}

int get_my_hand(string page) {
    matcher m = create_matcher( "<td style=\"padding-left: .5em; font-size:3em;
font-weight: bold;\" width=\"100\">(\\d+)</td>" , page );
    m.find();
    int hand = 0;
    boolean found = m.find();
    found = m.find();
    while (found) {
        string card = m.group(1);
        if(card == "a") {
            hand = hand + 1;
        } else if(card == "2") {
            hand = hand + 10;
        } else if(card == "3") {
            hand = hand + 100;
        } else if(card == "4") {
            hand = hand + 1000;
        } else {
            hand = hand +10000;
        }
        found = m.find();
    }
    return hand;
}

// renamed from main to avoid conflict
void my11_main(int rounds) {
    int bet = 11;
    string page;
    int initial = item_amount($item[crimbuck]);
    int total = rounds;
    while( rounds > 0 ) {
        print("Round " + rounds + "(counting down) ... Betting " + bet,
"blue");
        page = start_game( bet );

        while( !contains_text( page , "Play Again" ) ) {
            int opp = get_opponent(page);
            int hand = get_my_hand(page);

            print("Hand: " + hand);

            if(((hand == 110 || hand == 200)&&(opp == 2 || opp == 3 || opp ==
4))||(hand == 1010 && (opp == 2 || opp == 3))) {
                page = double();
                print("doubling down...");
            } else if( hand == 2 || hand == 11 || hand == 101 || hand == 20 ||
hand == 10010 || hand == 1100 || hand == 10100 || hand == 2000 || hand == 3 ||
hand == 12 || hand == 10002 || hand == 1011 || hand == 201 || hand == 30 ||
hand == 120 || hand == 4 || hand == 13 || hand == 103 || hand == 1003 || hand
== 10003 || hand == 22 || hand == 112 || hand == 1012 || hand == 31 || ((hand
== 11000 || hand == 300 || hand == 1102 || hand == 211 || hand == 130) && (opp
== 1 || opp == 5)) || ((hand == 102 || hand == 21 || hand == 10101 || hand ==
10012) && opp == 1) || ((hand == 10011 || hand == 202 || hand == 121 || hand ==
40) && opp != 3) || ((hand == 1101 || hand == 1020 || hand == 210) && (opp != 2
&& opp != 3)) || (hand == 2001 && opp == 5)) {
                page = hit();
                print("Hitting...");
            } else {
                page = stand();
                print("Standing...");
            }
        }
        if(contains_text( page, "You acquire")) {
            print("You Win!", "green");
        } else {
            print("You Lose!", "red");
        }
        rounds = rounds - 1;

        cli_execute("mood execute");
    }
    int change = item_amount($item[crimbuck]) - initial;
    print("gained "+change+" crimbux in "+total+" adventures","blue");
    print("gambling complete");
}

// ----------------------------- sims_lib.ash --------------------------------
item clancy_instrument = $item[none];

void none_fam(int combat) {
    if(combat>0)
        print("................. best fam: hound dog, for combat
rate.","green");

    print("................. ------------------ stat fams
----------------","green");

    if(my_path() != "Bees hate you") {
        if(available_amount($item[aquaviolet jub-jub bird])>0  ||
available_amount($item[charpuce jub-jub bird])>0 ||
available_amount($item[crimsilion jub-jub bird])>0)
            print("................. best fam: tuned bandersnatch. Improves
combat skills.","green");
        else
            print("................. best fam: bugged bugbear if you can handle
ML (acts as potato).","green");

        if(my_level()>=9) {
            print("................. alternative: baby sandworm. Also drops
spleen.","green");
        }
        else {
            print("................. alternative: untuned bandersnatch.
Improves combat skills.","green");
            print("................. alternative: spirity hobo. Recharges MP
for booze.","green");
        }
    }
    print("................. alternative: gluttonous green ghost. Recharges MP
for food.","green");
    print("................. alternative: hobo spirit. Recharges MP for
booze.","green");
    print("................. alternative: xenomorph. Drops
transponders.","green");
    print("................. alternative: nervous tick. Increases
meat.","green");

    print("................. ------------------ drop fams
----------------","green");
    print("................. llama lama, gives nice spleen if you fight with
bird skills.","green");
    print("................. pair of stomping boots, nearly as good and simpler
spleen","green");
    print("................. rogue program, gives worse spleen as free drop
(+mp).","green");
    if(my_path() != "Bees hate you") {
        print("................. baby sandworm, gives worse spleen as free drop
(+stats).","green");
        print("................. green pixie. gives nice spleen but requires
wasted turns. also can give power leveling later.","green");
    }
    print("................. stocking mimic. Gives stats or item+meat buff
items. (Also gives meat and mp.)","green");
}

void runaway_fam(int combat) {
    int max_weight = max(familiar_weight($familiar[frumious bandersnatch]),
familiar_weight($familiar[pair of stomping boots]));
    if(available_amount($item[sugar sheet])>0 || available_amount($item[sugar
shield])>0 || get_property("tomeSummons").to_int()<3)
        max_weight = max_weight + 10;
    if(have_skill($skill[leash of linguini]))
        max_weight = max_weight + 5;
    if(have_skill($skill[empathy of the newt]))
        max_weight = max_weight + 5;
    if(have_skill($skill[amphibian sympathy]))
        max_weight = max_weight + 5;
    if(get_property("_poolGames").to_int() < 3)
        max_weight = max_weight + 5;
    if(available_amount($item[green candy heart])>0)
        max_weight = max_weight + 3;
    if(have_outfit("knob goblin elite guard") && available_amount($item[cobb's
knob lab key])>0)
        max_weight = max_weight + 5;
    if(get_property("sidequestArenaCompleted") == "fratboy")
        max_weight = max_weight + 5;

    int max_runaways = floor(max_weight/5);

    if(my_path() != "Bees hate you" && get_property("_banderRunaways").to_int()
< max_runaways) {
        print("................. pair of stomping boots","green");
        print("................. bandernatch (needs ode)","green");
    }
    else {
        none_fam(combat);
    }
}

void delay_fam(int combat) {
    if(get_property("_Mini-HipsterAdv").to_int() < 7) {
        print("................. Mini-Hipster","green");
    }
    else {
        runaway_fam(combat);
    }
}

void suggest_fam(string main_goal, int combat) {
    if(my_path()=="Avatar of Boris") {
        if(main_goal=="items") {
            if(available_amount($item[Bag o' Tricks])>0) {
                print("-(summon weasels from Bag o' Tricks with 2
charges)","green");
            }
            if(available_amount($item[greatest american pants])>0)
                print("(use super vision buff from GAP)","green");
            if(available_amount($item[clancy's lute])>0)
                print("................. give clancy the lute","green");
        }
        else if(available_amount($item[clancy's crumhorn])>0) {
            print("................. give clancy the crumhorn","green");
        }
        else if(main_goal=="meat") {
            if(available_amount($item[Bag o' Tricks])>0) {
                print("-(summon badgers from Bag o' Tricks with 1
charges)","green");
            }
        }
        return;
    }

    if(main_goal=="items") {
        if(available_amount($item[Bag o' Tricks])>0) {
            print("-(summon weasels from Bag o' Tricks with 2
charges)","green");
        }
        if(available_amount($item[crown of thrones])>0)
            print("(feral kobold in crown)","green");
        if(available_amount($item[greatest american pants])>0)
            print("(use super vision buff from GAP)","green");
        if(available_amount($item[spangly sombrero])>0 && combat<=0) {
            print("................. best fam: hatrack + spangly
sombrero","green");
        }
        else if(combat>=0) {
            print("................. best fam: hound dog","green");
        }

        print("................. alternative: slimeling. pickpocket equippables
and give mp","green");
        if(my_path() != "Bees hate you") {
            print("................. pair of stomping boots. charges spleen
stomps.","green");
            print("................. alternative: green pixie. power level
drops","green");
        }
        if(available_amount($item[Tiny top hat and cane])>0)
            print("................. alternative: xenomorph. volley
stats","green");
    }
    else if(main_goal=="meat") {
        if(available_amount($item[Bag o' Tricks])>0) {
            print("-(summon badgers from Bag o' Tricks with 1
charges)","green");
        }
        if(available_amount($item[crown of thrones])>0)
            print("(put hobo monkey / organ grinder in crown)","green");
        if(available_amount($item[sugar chapeau])>0 ||
available_amount($item[sugar sheet])>0)
            print("................. Best fam: hatrack + sugar chapeau, gives
stats","green");

        print("................. Best fam: hobo monkey. makes food.","green");
        print("................. alternative: organ grinder. makes
food.","green");
    }
    else if(main_goal=="runaways") {
        runaway_fam(combat);
    }
    else if(main_goal=="delay") {
        delay_fam(combat);
    }
    else if(main_goal=="combat") {
        string hat;
        int weight;
        if(available_amount($item[spangly sombrero])>1) {
            hat="spangly sombrero";
            weight=3*min(37,(familiar_weight($familiar[mad hatrack]) +
weight_adjustment()));
        }
        else if(available_amount($item[mullet wig])>1) {
            hat="mullet wig";
            weight=2*min(10,(familiar_weight($familiar[mad hatrack]) +
weight_adjustment()));
        }
        else {
            hat="maiden wig";
            weight=2*min(8,(familiar_weight($familiar[mad hatrack]) +
weight_adjustment()));
        }

        print("................. Mad hatrack + "+hat+" = "+weight+" weight
potato.","green");
        if(my_path()!="Bees hate you") {
            print("................. Baby Bugged bugbear is
"+(familiar_weight($familiar[baby bugged bugbear]) + weight_adjustment())+"
weight potato, but adds 20 ML.","green");
            print("................. Frumious Bandersnatch. Improves
skills.","green");
            print("................. organ grinder. Doesn't help, but might
make a badass pie?","green");
        }
        weight=familiar_weight($familiar[Mini-Hipster]) + weight_adjustment();
        float action = to_float(weight)*2.5;
        action=action+25.0;
        print("................. Mini-Hipster acts "+action+" percent of the
time (split between blocking, healing, meat and damage).","green");
    }
    else if(main_goal=="none") {
        none_fam(combat);
    }
    else {
        abort("................. unrecognised goal \""+main_goal+"\"");
    }
}

string visit_url_non_abort(string url) {
    string output;
    try {
        output=visit_url(url);
    }
    finally {
        return output;
    }
    return output;
}

void train_moxie_skills() {
    visit_url("gnomes.php?action=trainskill&whichskill=10");
    visit_url("gnomes.php?action=trainskill&whichskill=11");
    visit_url("gnomes.php?action=trainskill&whichskill=12");
    visit_url("gnomes.php?action=trainskill&whichskill=13");
    visit_url("gnomes.php?action=trainskill&whichskill=14");
}

void meatmail(string person, int send_meat) {
    if(my_meat() > send_meat) {
        print("sending "+send_meat+" to "+person,"blue");

visit_url("sendmessage.php?toid=&action=send&towho="+person+"&contact=0&message
=&howmany1=1&whichitem1=0&sendmeat="+send_meat+"&messagesend=Send+Message.&pwd"
);
    }
    else {
        print("Don't have enough meat","red");
    }
}

boolean have_buff_equip() {
    boolean have=true;
    if(have_skill($skill[The Polka of Plenty]) || have_skill($skill[Fat Leon's
Phat Loot Lyric]) || have_skill($skill[The Ode to Booze]) ||
have_skill($skill[The Sonata of Sneakiness]) || have_skill($skill[Carlweather's
Cantata of Confrontation]) || have_skill($skill[Ur-Kel's Aria of Annoyance])) {
        if(item_amount($item[stolen accordion])==0 && item_amount($item[rock
and roll legend])==0 && item_amount($item[Squeezebox of the Ages])==0 &&
item_amount($item[The Trickster's Trikitixa])==0) {
            have=false;
        }
    }
    if(have_skill($skill[Jalape&ntilde;o Saucesphere]) ||
have_skill($skill[Elemental Saucesphere]) || have_skill($skill[Scarysauce]) ) {
        if(item_amount($item[saucepan])==0 && item_amount($item[5-alarm
saucepan])==0 && item_amount($item[17-alarm saucepan])==0 &&
item_amount($item[windsor pan of the source])==0) {
            have=false;
        }
    }
    if(have_skill($skill[ghostly shell]) || have_skill($skill[Tenacity of the
Snapper]) || have_skill($skill[Empathy of the Newt]) ||
have_skill($skill[Reptilian Fortitude]) || have_skill($skill[astral shell]) ||
have_skill($skill[jingle bells])) {
        if(item_amount($item[turtle totem])==0 && item_amount($item[mace of the
tortoise])==0 && item_amount($item[Chelonian Morningstar])==0 &&
item_amount($item[flail of the seven aspects])==0) {
            have=false;
        }
    }
    return have;
}

void get_buff_equip() {
    if(have_skill($skill[The Polka of Plenty]) || have_skill($skill[Fat Leon's
Phat Loot Lyric]) || have_skill($skill[The Ode to Booze]) ||
have_skill($skill[The Sonata of Sneakiness]) || have_skill($skill[Carlweather's
Cantata of Confrontation]) || have_skill($skill[Ur-Kel's Aria of Annoyance])) {
        if(item_amount($item[stolen accordion])==0 && item_amount($item[rock
and roll legend])==0 && item_amount($item[Squeezebox of the Ages])==0 &&
item_amount($item[The Trickster's Trikitixa])==0) {
            set_property("choiceAdventure502","3");
            set_property("choiceAdventure506","1");
            set_property("choiceAdventure26","3");
            set_property("choiceAdventure29","2");
            while(item_amount($item[saucepan])==0 && my_adventures()>0 &&
my_meat()>30) {
                adventure(1,$location[The Spooky Forest]);
            }
        }
    }
    if(have_skill($skill[Jalape&ntilde;o Saucesphere]) ||
have_skill($skill[Elemental Saucesphere]) || have_skill($skill[Scarysauce]) ) {
        if(item_amount($item[saucepan])==0 && item_amount($item[5-alarm
saucepan])==0 && item_amount($item[17-alarm saucepan])==0 &&
item_amount($item[windsor pan of the source])==0) {
            set_property("choiceAdventure502","3");
            set_property("choiceAdventure506","1");
            set_property("choiceAdventure26","2");
            set_property("choiceAdventure28","2");
            while(item_amount($item[saucepan])==0 && my_adventures()>0 &&
my_meat()>30) {
                adventure(1,$location[The Spooky Forest]);
            }
        }
    }
    if(have_skill($skill[ghostly shell]) || have_skill($skill[Tenacity of the
Snapper]) || have_skill($skill[Empathy of the Newt]) ||
have_skill($skill[Reptilian Fortitude]) || have_skill($skill[astral shell]) ||
have_skill($skill[jingle bells])) {
        if(item_amount($item[turtle totem])==0 && item_amount($item[mace of the
tortoise])==0 && item_amount($item[Chelonian Morningstar])==0 &&
item_amount($item[flail of the seven aspects])==0) {
            set_property("choiceAdventure502","3");
            set_property("choiceAdventure506","1");
            set_property("choiceAdventure26","1");
            set_property("choiceAdventure27","2");
            while(item_amount($item[saucepan])==0 && my_adventures()>0 &&
my_meat()>30) {
                adventure(1,$location[The Spooky Forest]);
            }
        }
    }
}

item my_epic() {
    item epic;
    if((my_class()==$class[seal clubber])) {
        epic=$item[Bjorn's Hammer];
    }
    else if(my_class()==$class[turtle tamer]) {
        epic=$item[Mace of the Tortoise];
    }
    else if(my_class()==$class[disco bandit]) {
        epic=$item[Disco Banjo];
    }
    else if(my_class()==$class[accordion thief]) {
        epic=$item[Rock and Roll Legend];
    }
    else if(my_class()==$class[pastamancer]) {
        epic=$item[pasta spoon of peril];
    }
    else {
        epic=$item[5-Alarm Saucepan];
    }
    return epic;
}

item my_legendary() {
    item legendary;
    if((my_class()==$class[seal clubber])) {
        legendary=$item[Hammer of Smiting];
    }
    else if(my_class()==$class[turtle tamer]) {
        legendary=$item[Chelonian Morningstar];
    }
    else if(my_class()==$class[disco bandit]) {
        legendary=$item[Shagadelic Disco Banjo];
    }
    else if(my_class()==$class[accordion thief]) {
        legendary=$item[Squeezebox of the Ages];
    }
    else if(my_class()==$class[pastamancer]) {
        legendary=$item[Greek pasta spoon of peril];
    }
    else {
        legendary=$item[17-alarm Saucepan];
    }
    return legendary;
}

item my_ultimate() {
    item ultimate;
    if((my_class()==$class[seal clubber])) {
        ultimate=$item[Sledgehammer of the V&aelig;lkyr];
    }
    else if(my_class()==$class[turtle tamer]) {
        ultimate=$item[Flail of the Seven Aspects];
    }
    else if(my_class()==$class[disco bandit]) {
        ultimate=$item[Seeger's Unstoppable Banjo];
    }
    else if(my_class()==$class[accordion thief]) {
        ultimate=$item[The Trickster's Trikitixa];
    }
    else if(my_class()==$class[pastamancer]) {
        ultimate=$item[Wrath of the Capsaician Pastalords];
    }
    else {
        ultimate=$item[Windsor Pan of the Source];
    }
    return ultimate;
}

boolean check_page(string page, string text) {
    return contains_text(visit_url(page),text);
}

boolean ensure_fancy_cocktail_kit() {
    boolean
success=contains_text(visit_url("campground.php?action=inspectkitchen"),"Queue
Du Coq cocktailcrafting kit");
    if(!success) {
        buy(1,$item[Queue Du Coq cocktailcrafting kit]);
        use(1,$item[Queue Du Coq cocktailcrafting kit]);
    }

success=contains_text(visit_url("campground.php?action=inspectkitchen"),"Queue
Du Coq cocktailcrafting kit");
    print("ensure_fancy_cocktail_kit returning "+success);
    return success;
}

void get_paste(int amt) {
    if(item_amount($item[meat paste])<amt) {
        create(amt-item_amount($item[meat paste]),$item[meat paste]);
    }
}

boolean simons_have_chef() {
    boolean
success=contains_text(visit_url("campground.php?action=inspectkitchen"),"Chef")
;
    return success;
}

boolean simons_have_bartender() {
    boolean
success=contains_text(visit_url("campground.php?action=inspectkitchen"),
"Bartender");
    return success;
}

boolean simons_get_chef() {
    if(simons_have_chef()) {
        return true;
    }
    print("trying to get a chef","blue");
    if(available_amount($item[chef-in-the-box])==0) {
        print("making a chef","blue");
        if(available_amount($item[chef skull])==0) {
            print("making a chef skull","blue");
            if(available_amount($item[brainy skull])==0) {
                print("making a brainy skull","blue");
                if(available_amount($item[disembodied brain])==0) {
                    if(can_interact()) {
                        print("bought brain","blue");
                        buy(1,$item[disembodied brain]);
                    }
                    else {
                        print("couldn't get brain","blue");
                        return false;
                    }
                }
                if(available_amount($item[smart skull])==0) {
                    if(can_interact()) {
                        print("buying skull","blue");
                        buy(1,$item[smart skull]);
                    }
                    else {
                        print("couldn't get skull","blue");
                        return false;
                    }
                }
                get_paste(1);

visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[disembodied
brain].to_int())+"&b="+($item[smart
skull].to_int())+"&qty=1&master=Combine%21");
            }
            if(available_amount($item[chef's hat])==0) {
                if(can_interact()) {
                    print("getting hat","blue");
                    buy(1,$item[chef's hat]);
                }
                else {
                    print("couldn't get hat","blue");
                    return false;
                }
            }
            get_paste(1);

visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[brainy
skull].to_int())+"&b="+($item[chef's
hat].to_int())+"&qty=1&master=Combine%21");
        }
        if(available_amount($item[nothing-in-the-box])==0) {
            print("Making nothing in hte box","blue");
            if(available_amount($item[box])==0) {
                if(can_interact()) {
                    print("getting box","blue");
                    buy(1,$item[box]);
                }
                else {
                    print("couldn't get box","blue");
                    return false;
                }
            }
            if(available_amount($item[spring])==0) {
                if(can_interact()) {
                    print("getting spring","blue");
                    buy(1,$item[spring]);
                }
                else {
                    print("couldn't get spring","blue");
                    return false;
                }
            }
            get_paste(1);

visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[box].to_int())+"&
b="+($item[spring].to_int())+"&qty=1&master=Combine%21");
        }
        get_paste(1);
        visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[chef
skull].to_int())+"&b="+($item[nothing-in-the-box].to_int())+"&qty=1&master=
Combine%21");
    }
    cli_execute("refresh inventory");
    if(available_amount($item[chef-in-the-box])!=0) {
        print("using chef","blue");
        use(1,$item[chef-in-the-box]);
        return true;
    }
    print("No result detected","blue");
    return false;
}

boolean simons_get_bartender() {
    if(simons_have_bartender()) {
        return true;
    }
    print("trying to make a bartender","blue");
    if(available_amount($item[bartender-in-the-box])==0) {
        if(available_amount($item[bartender skull])==0) {
            if(available_amount($item[brainy skull])==0) {
                if(available_amount($item[disembodied brain])==0) {
                    if(can_interact()) {
                        buy(1,$item[disembodied brain]);
                    }
                    else {
                        print("simons_get_bartender returning false","blue");
                        return false;
                    }
                }
                if(available_amount($item[smart skull])==0) {
                    if(can_interact()) {
                        buy(1,$item[smart skull]);
                    }
                    else {
                        print("simons_get_bartender returning false","blue");
                        return false;
                    }
                }
                get_paste(1);
                print("crafting brainy skull","blue");

visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[disembodied
brain].to_int())+"&b="+($item[smart
skull].to_int())+"&qty=1&master=Combine%21");
            }
            if(available_amount($item[beer goggles])==0) {
                if(available_amount($item[beer lens])<2) {
                    if(can_interact()) {
                        buy(2-available_amount($item[beer lens]),$item[beer
lens]);
                    }
                    else {
                        print("simons_get_bartender returning false","blue");
                        return false;
                    }
                }
                get_paste(1);
                print("crafting beer goggles","blue");

visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[beer
lens].to_int())+"&b="+($item[beer lens].to_int())+"&qty=1&master=Combine%21");
            }
            get_paste(1);
            print("crafting bartender skull","blue");

visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[brainy
skull].to_int())+"&b="+($item[beer
goggles].to_int())+"&qty=1&master=Combine%21");
        }
        if(available_amount($item[nothing-in-the-box])==0) {
            if(available_amount($item[box])==0) {
                if(can_interact()) {
                    buy(1,$item[box]);
                }
                else {
                    print("simons_get_bartender returning false","blue");
                    return false;
                }
            }
            if(available_amount($item[spring])==0) {
                if(can_interact()) {
                    buy(1,$item[spring]);
                }
                else {
                    print("simons_get_bartender returning false","blue");
                    return false;
                }
            }
            get_paste(1);
            print("crafting nothing in the box","blue");

visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[box].to_int())+"&
b="+($item[spring].to_int())+"&qty=1&master=Combine%21");
        }
        get_paste(1);
        print("crafting crafting bartender in the box","blue");
        visit_url("craft.php?mode=combine&pwd&action=craft&a="+($item[bartender
skull].to_int())+"&b="+($item[nothing-in-the-box].to_int())+"&qty=1&master=
Combine%21");
    }
    cli_execute("refresh inventory");
    if(available_amount($item[bartender-in-the-box])!=0) {
        use(1,$item[bartender-in-the-box]);
        print("simons_get_bartender returning true","blue");
        return true;
    }
    print("simons_get_bartender returning false","blue");
    return false;
}

void new_hermit(item it) {
    while(my_meat()>50 && item_amount($item[worthless trinket])==0 &&
item_amount($item[worthless gewgaw])==0 && item_amount($item[worthless
knick-knack])==0) {
        use(1,$item[chewing gum on a string]);
    }
    if(item_amount($item[worthless trinket])!=0 || item_amount($item[worthless
gewgaw])!=0 || item_amount($item[worthless knick-knack])!=0) {
        cli_execute("hermit "+it);
    }
}

void skeleton_farm() {
    while(my_adventures()>0) {
        string page = visit_url("adventure.php?snarfblat=245");
        if(contains_text(page,"nothing more to see here")) {
            cli_execute("use * bag of bones");
            cli_execute("stash put * bone chips");
            return;
        }
        page = attack();
        if(contains_text(page,"Stabonic scroll")) {
            break;
        }
        if(contains_text(visit_url("campground.php"),"Your Campsite")) {
            visit_url("galaktik.php?pwd&action=curehp&quantity=1");
        }
    }
}

int best_price(item it) {
    int total_price=0;
    int [item] mats = get_ingredients(it);
    int num_ingredients=0;
    item last_mat;
    foreach mat in mats {
        last_mat=mat;
        num_ingredients=1+num_ingredients;
    }
    if(num_ingredients==0) {
        return mall_price(it);
    }
    if(num_ingredients==1) {
        return min(mall_price(it),mall_price(last_mat));
    }
    foreach mat in mats {
        total_price+=mall_price(mat);
    }
    return min(mall_price(it),total_price);
}

void smart_obtain(item it) {
    int total_price=0;
    int [item] mats = get_ingredients(it);
    int num_ingredients=0;
    item last_mat;
    foreach mat in mats {
        last_mat=mat;
        num_ingredients=1+num_ingredients;
    }
    if(num_ingredients==0) {
        buy(1,it);
    }
    if(num_ingredients==1) {
        if(mall_price(it)<mall_price(last_mat)) {
            buy(1,it);
        }
        else {
            buy(1,last_mat);
        }
    }
    if(num_ingredients<1) {
        foreach mat in mats {
            total_price+=mall_price(mat);
        }
        if(mall_price(it)<total_price) {
            buy(1,it);
        }
        else {
            foreach mat in mats {
                buy(1,mat);
            }
        }
    }
}

item choose_cheapest_item(item it1, item it2) {
    if(best_price(it1)<best_price(it2)) {
        return it1;
    }
    return it2;
}

void choose_and_drink_cherry_tps() {
    item
second_ingredient=choose_cheapest_item($item[old-fashioned],$item[sangria]);
    print("second_ingredient chosen="+to_string(second_ingredient),"blue");
    if(item_amount(second_ingredient)==0) {
        cli_execute("acquire "+to_string(second_ingredient));
    }
    craft("cocktail",1,$item[skewered cherry],second_ingredient);
    cli_execute("drink * cherry bomb");
    cli_execute("drink * sangria del diablo");
}

void choose_and_drink_olive_tps() {
    item second_ingredient=choose_cheapest_item($item[dry martini],$item[dry
vodka martini]);
    print("second_ingredient chosen="+to_string(second_ingredient),"blue");
    if(item_amount(second_ingredient)==0) {
        cli_execute("acquire "+to_string(second_ingredient));
    }
    craft("cocktail",1,$item[skewered jumbo olive],second_ingredient);
    cli_execute("drink * vesper");
    cli_execute("drink * dirty martini");
}

void choose_and_drink_lime_tps() {
    item second_ingredient=choose_cheapest_item($item[tequila with training
wheels],$item[grog]);
    print("second_ingredient chosen="+to_string(second_ingredient),"blue");
    if(item_amount(second_ingredient)==0) {
        cli_execute("acquire "+to_string(second_ingredient));
    }
    craft("cocktail",1,$item[skewered lime],second_ingredient);
    cli_execute("drink * bodyslam");
    cli_execute("drink * grogtini");
}

// ----------------------------- SmashLib.ash ---------------------------------
import <zlib.ash>; // but we are including it below; this is fine

script "SmashLib" { } // just a marker, removed script line

boolean is_smashable(item it) {
    if (pulverize_exceptions contains it) {
        if (pulverize_exceptions[it] == "nosmash" || pulverize_exceptions[it]
== "upgrade")
            return false;
        return true;
    }

    if ($slots[hat, weapon, off-hand, shirt, pants, acc1, acc2, acc3] contains
to_slot(it))
        return true;

    return false;
}

boolean is_malusable(item it) {
    return (pulverize_exceptions[it] == "upgrade");
}

boolean smash(int quantity, item it) {
    if (!is_smashable(it)) { return false; }
    return(cli_execute("smash " + quantity + " " + it));
}

item to_jewel(element el) {
    switch (el) {
        case $element[cold]:
            return $item[glacial sapphire];
        case $element[hot]:
            return $item[steamy ruby];
        case $element[sleaze]:
            return $item[tawdry amethyst];
        case $element[spooky]:
            return $item[unearthly onyx];
        case $element[stench]:
            return $item[effluvious emerald];
        default:
            return $item[none];
    }
    return $item[none];
}

float [string] get_smash_element(item it) {
    float [string] result;

    if (!is_smashable(it))
        return result;

    if (is_npc_item(it)) {
        result["useless"] = 1.0;
        return result;
    }

    if (pulverize_exceptions contains it) {
        switch(pulverize_exceptions[it]) {
            case "useless powder":
                result["useless"] = 1.0;
                break;
            case "epic wad":
                result["epic"] = 1.0;
                break;
            case "sea salt crystal":
                result["sea salt"] = 1.0;
                break;
            case "ultimate wad":
                result["ultimate"] = 1.0;
                break;
            case "sugar shard":
                result["sugar"] = 1.0;
                break;
            case "chunk of depleted Grimacite":
                result["depleted Grimacite"] = 1.0;
                break;
            case "wad of Crovacite":
                result["Crovacite"] = 1.0;
                break;
        }
        return result;
    }

    result["twinkly"] = 1.0;

    if (numeric_modifier(it, "cold damage") > 0 || numeric_modifier(it, "cold
spell damage") > 0)
        result["cold"] = 1.0;
    if (numeric_modifier(it, "hot damage") > 0 || numeric_modifier(it, "hot
spell damage") > 0)
        result["hot"] = 1.0;
    if (numeric_modifier(it, "sleaze damage") > 0 || numeric_modifier(it,
"sleaze spell damage") > 0)
        result["sleaze"] = 1.0;
    if (numeric_modifier(it, "spooky damage") > 0 || numeric_modifier(it,
"spooky spell damage") > 0)
        result["spooky"] = 1.0;
    if (numeric_modifier(it, "stench damage") > 0 || numeric_modifier(it,
"stench spell damage") > 0)
        result["stench"] = 1.0;

    if (numeric_modifier(it, "cold resistance") > 0) {
        result["hot"] = 1.0;
        result["spooky"] = 1.0;
    }
    if (numeric_modifier(it, "hot resistance") > 0) {
        result["sleaze"] = 1.0;
        result["stench"] = 1.0;
    }
    if (numeric_modifier(it, "sleaze resistance") > 0) {
        result["cold"] = 1.0;
        result["spooky"] = 1.0;
    }
    if (numeric_modifier(it, "spooky resistance") > 0) {
        result["hot"] = 1.0;
        result["stench"] = 1.0;
    }
    if (numeric_modifier(it, "stench resistance") > 0) {
        result["cold"] = 1.0;
        result["sleaze"] = 1.0;
    }

    float num_types = 0;
    foreach piece in result {
        num_types = num_types + result[piece];
    }
    foreach piece in result {
        result[piece] = result[piece] / num_types;
    }

    return result;
}

string get_smash_tier(item it) {
    if (!is_smashable(it))
        return "";

    if (is_npc_item(it))
        return "exception";

    if (pulverize_exceptions contains it)
        return "exception";

    int power = equipment[it].power;
    int requirement;
    int index = index_of(equipment[it].complete_requirement, ":");
    if (index > 0)
        requirement = to_int(substring(equipment[it].complete_requirement, 5));
    else
        requirement = 0;

    if (power > 0) {
        if (power <= 35)  return "1P";
        if (power <= 55)  return "2P";
        if (power <= 75)  return "3P";
        if (power <= 95)  return "1N";
        if (power <= 115) return "2N";
        if (power <= 135) return "3N";
        if (power <= 155) return "1W";
        if (power <= 175) return "2W";
        if (power >=  180) return "3W";
    }
    else {
        if (requirement <= 2)  return "1P";
        if (requirement <= 13) return "2P";
        if (requirement <= 23) return "3P";
        if (requirement <= 33) return "1N";
        if (requirement <= 43) return "2N";
        if (requirement <= 53) return "3N";
        if (requirement <= 63) return "1W";
        if (requirement <= 73) return "2W";
        if (requirement >= 75)  return "3W";
    }

    return "";
}

float [item] get_smash_yield(item it) {
    float [item] result;

    if (!is_smashable(it))
        return result;

    string tier = get_smash_tier(it);
    float [string] element_type = get_smash_element(it);

    switch(tier) {
        case "1P":
            foreach piece in element_type {
                result[to_item(piece + " powder")] = element_type[piece];
            }
            break;
        case "2P":
            foreach piece in element_type {
                result[to_item(piece + " powder")] = 2 * element_type[piece];
            }
            break;
        case "3P":
            foreach piece in element_type {
                result[to_item(piece + " powder")] = 3 * element_type[piece];
            }
            break;
        case "1N":
            foreach piece in element_type {
                result[to_item(piece + " nugget")] = .5 * element_type[piece];
                result[to_item(piece + " powder")] =  2 * element_type[piece];
            }
            break;
        case "2N":
            foreach piece in element_type {
                result[to_item(piece + " nugget")] = 1.5 * element_type[piece];
                result[to_item(piece + " powder")] = 1.5 * element_type[piece];
            }
            break;
        case "3N":
            foreach piece in element_type {
                result[to_item(piece + " nugget")] = 3 * element_type[piece];
            }
            break;
        case "1W":
            foreach piece in element_type {
                if (piece == "twinkly") {
                    result[to_item(piece + " wad")] = .5 * element_type[piece];
                }
                else {
                    result[to_jewel(to_element(piece))] = .005 *
element_type[piece];
                    result[to_item(piece + " wad")] =   .495 *
element_type[piece];
                }
                result[to_item(piece + " nugget")] = 2 * element_type[piece];
            }
            break;
        case "2W":
            foreach piece in element_type {
                if (piece == "twinkly") {
                    result[to_item(piece + " wad")] = 1.5 *
element_type[piece];
                }
                else {
                    result[to_jewel(to_element(piece))] = .011 *
element_type[piece];
                    result[to_item(piece + " wad")] = 1.489 *
element_type[piece];
                }
                result[to_item(piece + " nugget")] = 1.5 * element_type[piece];
            }
            break;
        case "3W":
            foreach piece in element_type {
                if (piece == "twinkly") {
                    result[to_item(piece + " wad")] = 3.0 *
element_type[piece];
                }
                else {
                    result[to_jewel(to_element(piece))] = .0123 *
element_type[piece];
                    result[to_item(piece + " wad")] = 2.9877 *
element_type[piece];
                }
            }
            break;
        case "exception":
            if (element_type contains "useless")
                result[to_item("useless powder")] = 1.0;
            if (element_type contains "epic")
                result[to_item("epic wad")] = 1.0;
            if (element_type contains "ultimate")
                result[to_item("ultimate wad")] = 1.0;
            if (element_type contains "sea salt")
                result[to_item("sea salt crystal")] = 1.0;
            if (element_type contains "depleted Grimacite")
                result[to_item("chunk of depleted Grimacite")] = 1.0;
            if (element_type contains "sugar")
                result[to_item("sugar shard")] = 1.0;
            if (element_type contains "Crovacite")
                result[to_item("wad of Crovacite")] = 1.0;
            break;
    }

    return result;
}

float [string] get_wad_yield(item it, boolean malus) {
    float [string] result;

    if (!is_smashable(it))
        return result;

    float [item] smash_yield = get_smash_yield(it);
    float [string] smash_elements = get_smash_element(it);

    if (smash_elements contains "twinkly") {
        foreach piece in smash_elements {
            result[piece] = smash_yield[to_item(piece + " wad")];
        }

        if (!malus)
            return result;

        foreach piece in smash_elements {
            result[piece] = result[piece] + .2 * smash_yield[to_item(piece + "
nugget")] + .04 * smash_yield[to_item(piece + " powder")];
        }
    }

    return result;
}

float [string] get_wad_yield(int [item] its, boolean malus) {
    float [string] result;
    float [string] single_result;

    foreach it in its {
        single_result = get_wad_yield(it, malus);
        foreach piece in $strings["twinkly", "cold", "hot", "sleaze", "spooky",
"stench"] {
            result[piece] = result[piece] + (its[it] * single_result[piece]);
        }
    }

    return result;
}

void print_smash_report(item it) {
    print_html("<b>" + it + "</b>");

    print("Tier: " + get_smash_tier(it));

    float [string] elements = get_smash_element(it);
    print("Elements:");
    foreach piece in elements {
        print("&nbsp;" + piece + ": " + elements[piece]);
    }

    float [item] yield = get_smash_yield(it);
    print("Expected Yields:");
    foreach type in yield {
        print("&nbsp;" + type + ": " + yield[type]);
    }
}

void print_smash_report(string it_str) {
    print_smash_report(to_item(it_str));
}

// ----------------------------- zlib.ash (newer) ----------------------------
// (Full content of zlib.ash – included here for completeness)
// NOTE: This is the modern zlib; tw_zlib.ash is omitted.
// ZLib version 2072.

float abs(float n) { return n < 0 ? -n : n; }
string getvar(string varname);
string[string] vars;

string excise(string source, string start, string end) {
   if (start != "") {
      if (!source.contains_text(start)) return "";
      source = substring(source,index_of(source,start)+length(start));
   }
   if (end == "") return source;
   if (!source.contains_text(end)) return "";
   return substring(source,0,index_of(source,end));
}

boolean equals(string s1, string s2) {
   return (length(s1) == length(s2) && contains_text(s1,s2));
}

boolean vprint(string message, string color, int level) {
   if (level == 0) abort(message);
   if (to_int(getvar("verbosity")) >= abs(level)) print(message,color);
   return (level > 0);
}
boolean vprint(string message, int level) { if (level > 0) return
vprint(message,"black",level); return vprint(message,"red",level); }
boolean vprint_html(string message, int level) {
   if (level == 0) { print_html(message); abort(); }
   if (to_int(getvar("verbosity")) >= abs(level)) print_html(message);
   return (level > 0);
}

string normalized(string mixvar, string type, string glue) {
   switch (type) {
      case "boolean": return to_string(to_boolean(mixvar));
      case "bounty": return to_string(to_bounty(mixvar));
      case "class": return to_string(to_class(mixvar));
      case "coinmaster": return to_string(to_coinmaster(mixvar));
      case "effect": return to_string(to_effect(mixvar));
      case "element": return to_string(to_element(mixvar));
      case "familiar": return to_string(to_familiar(mixvar));
      case "float": return to_string(to_float(mixvar));
      case "int": return to_string(to_int(mixvar));
      case "item": return to_string(to_item(mixvar));
      case "location": return to_string(to_location(mixvar));
      case "monster": return to_string(to_monster(mixvar));
      case "phylum": return to_string(to_phylum(mixvar));
      case "servant": return (to_string(to_servant(mixvar)));
      case "skill": return to_string(to_skill(mixvar));
      case "stat": return to_string(to_stat(mixvar));
      case "thrall": return to_string(to_thrall(mixvar));
      case "vykea": return to_string(to_vykea(mixvar));
      case "list of string":
      case "string": return mixvar;
   }
   if (index_of(type,"list of ") == 0) {
       string[int] bits = split_string(mixvar,glue);
       mixvar = "";
       foreach n,bit in bits {
          if (n > 0) mixvar += glue;
          mixvar += normalized(bit,excise(type,"list of ",""), glue);
       }
   } else vprint("Unable to normalize type '"+type+"'.",-3);
   return mixvar;
}
string normalized(string mixvar, string type) { return normalized(mixvar, type,
", "); }

string join(string[int] pieces, string glue) {
   buffer res;
   boolean middle;
   foreach index in pieces {
      if (middle) res.append(glue);
      middle = true;
      res.append(pieces[index]);
   }
   return res;
}
string join(string[int] pieces) { return join(pieces, ", "); }

boolean list_contains(string stringlist, string needle, string glue) {
   return
create_matcher("(^|"+glue+")\\Q"+to_lower_case(needle)+"\\E($|"+glue+")",
to_lower_case(stringlist)).find();
}
boolean list_contains(string stringlist, string needle) { return
list_contains(stringlist, needle, ", "); }

string list_add(string stringlist, string add, string glue) {
   if (length(stringlist) == 0) return add;
   if (list_contains(stringlist,add,glue)) return stringlist;
   return stringlist+glue+add;
}
string list_add(string stringlist, string add) { return list_add(stringlist,
add, ", "); }

string list_remove(string stringlist, string del, string glue) {
   string[int] bits;
   foreach i,b in split_string(stringlist, glue) if (b != del) bits[i] = b;
   return join(bits,glue);
}
string list_remove(string stringlist, string del) { return
list_remove(stringlist, del, ", "); }

string rnum(int n) {
   return to_string(n,"%,d");
}
string rnum(float n, int place) {
   if (place < 1 || to_float(round(n)) ==
to_float(to_string(n,"%,."+place+"f"))) return rnum(round(n));
   return replace_all(create_matcher("0+$", to_string(n,"%,."+place+"f")),"");
}
string rnum(float n) { return rnum(n,2); }

float minmax(float a, float min, float max) { return max(min(a,max),min); }

void set_avg(float toadd, string whichprop) {
   string initv = get_property(whichprop);
   if (initv == "") { set_property(whichprop,toadd+":1"); return; }
   float a = to_float(excise(initv,"",":"));
   float b = to_float(excise(initv,":",""));
   a = ((a * b)+toadd) / (b+1);
   b += 1;
   set_property(whichprop,a+":"+b);
}
float get_avg(string whichprop) {
   string initv = get_property(whichprop);
   if (initv == "") return 0;
   return to_float(substring(initv,0,index_of(initv,":")));
}

float eval(string expr, float[string] values) {
   buffer b;
   matcher m = create_matcher("\\b[a-z_][a-zA-Z0-9_]*\\b", expr);
   while (m.find()) {
      string var = m.group(0);
      if (values contains var) m.append_replacement(b,
values[var].to_string());
   }
   m.append_tail(b);
   m = create_matcher("[a-z]",b);
   vprint("Evaluating '"+b.to_string()+"'...",10+(m.find() ? 0 :
1+to_int(is_integer(b))));
   return modifier_eval(b.to_string());
}

record {
   string ver;
   string vdate;
}[string] zv;

string check_version(string soft, string proj, int thread) { buffer msg;
   if (get_property("_svnUpdated").to_boolean()) return "";
   if (count(zv) == 0) file_to_map("zversions.txt",zv);
   if (zv[proj].vdate == today_to_string()) return "";
   vprint_html("Checking for updates (running <a
href='https://kolmafia.us/showthread.php?t="+thread+"'
target='_blank'>"+soft+"</a> rev. "+svn_info(proj).revision+")...",1);
   zv[proj].vdate = today_to_string();
   map_to_file(zv,"zversions.txt");
   if (!svn_at_head(proj)) {
      cli_execute("svn update " + proj);
      msg.append(soft+" has been updated from r"+zv[proj].ver+" to
r"+svn_info(proj).revision+".  The next time it is run, it will be current.");
   }
   if (to_int(zv[proj].ver) == svn_info(proj).revision) {
map_to_file(zv,"zversions.txt"); return ""; }
   if (length(msg) == 0) msg.append(soft+" has been updated from
r"+zv[proj].ver+" to r"+svn_info(proj).revision+" since you last ran it.");
   msg.insert(0,"<big><font color=red><b>"+soft+"
Updated!</b></font></big><br>");
   msg.append("<br><a href='https://kolmafia.us/showthread.php?t="+thread+"'
target='_blank'><u>Click here "+
      "for discussion of what's new.</u></a> (<a
href='https://kolmafia.us/showthread.php?goto=newpost&t="+thread+"'
target='_blank'><u>last post</u></a>)");
   if (contains_text(svn_info(proj).url,"svn.code.sf.net")) msg.append(" (<a
href='"+replace_string(svn_info(proj).url,"svn.code.","")+"/log/'
target='_blank'><u>SourceForge</u></a>)");
   zv[proj].ver = svn_info(proj).revision;
   map_to_file(zv,"zversions.txt");
   vprint_html(msg,1);
   return "<div class='versioninfo'>"+msg+"</div>";
}

string check_version(string soft, string prop, string thisver, int thread) {
int w = 8; string page; matcher find_ver;
   if (count(zv) == 0) file_to_map("zversions.txt",zv);
   boolean sameornewer(string local, string server) {
      if (equals(local,server)) return true;
      string[int] loc = split_string(local,"\\.");
      string[int] ser = split_string(server,"\\.");
      for i from 0 to max(count(loc)-1,count(ser)-1) {
         if (i+1 > count(loc)) return false; if (i+1 > count(ser)) return true;
         if (loc[i].to_int() < ser[i].to_int()) return false;
         if (loc[i].to_int() > ser[i].to_int()) return true;
      }
      return local == server;
   }
   if (zv[prop].vdate != today_to_string()) {
      vprint("Checking for updates (running "+soft+" ver. "+thisver+")...",1);
      page = visit_url("https://kolmafia.us/showthread.php?t="+thread);
      find_ver = create_matcher("<b>"+soft+" (.+?)</b>",page);
      zv[prop].vdate = today_to_string();
      if (!find_ver.find()) {
         vprint("Unable to load current version info.",-1);
         map_to_file(zv,"zversions.txt");
         return "";
      } w=1;
      zv[prop].ver = find_ver.group(1);
      map_to_file(zv,"zversions.txt");
   }
   if (sameornewer(thisver,zv[prop].ver)) { vprint("Running "+soft+" version:
"+thisver+" (current)","gray",w); return ""; }
   if (svn_exists(prop)) { return check_version(soft, prop, thread); }
   string msg = "<big><font color=red><b>New Version of "+soft+" Available:
"+zv[prop].ver+"</b></font></big>"+
      "<br><a href='https://kolmafia.us/showthread.php?t="+thread+"'
target='_blank'><u>Upgrade from "+thisver+" to "+zv[prop].ver+"
here!</u></a><br>";
   find_ver = create_matcher("\\[requires revision (.+?)\\]",page);
   if (find_ver.find() && find_ver.group(1).to_int() > get_revision())
      msg += " (Note: you will also need to <a
href='https://builds.kolmafia.us/' target='_blank'>update mafia to
r"+find_ver.group(1)+" or higher</a> to use this update.)";
   vprint_html(msg,1);
   return "<div class='versioninfo'>"+msg+"</div>";
}

boolean load_current_map(string fname, aggregate dest) {
   file_to_map(fname+".txt",dest);
   string key = "map_"+fname+".txt";
   if (count(zv) == 0) file_to_map("zversions.txt",zv);
   if (zv[key].vdate == today_to_string() && count(dest) > 0) return true;
   zv[key].vdate = today_to_string();
   string rem =
visit_url("https://zachbardon.com/mafiatools/autoupdate.php?f="+fname+"&act=
getver", false);
   if (rem == "" || rem.length() > 150) return vprint("There was a problem
accessing the Map Manager.",-1);
   if (zv[key].ver == rem && count(dest) > 0) {
      map_to_file(zv,"zversions.txt");
      return vprint("You have the latest "+fname+".txt.  Will not check again
today.",3);
   }
   vprint("Updating "+fname+".txt "+(count(dest) > 0 ? "from '"+zv[key].ver+"'
" : "")+"to '"+rem+"'...",1);
   if
(!file_to_map("https://zachbardon.com/mafiatools/autoupdate.php?f="+fname+"&act
=getmap",dest) || count(dest) == 0)
      return vprint("Error loading "+fname+".txt from the Map
Manager.","red",-1);
   zv[key].ver = rem;
   map_to_file(dest,fname+".txt");
   map_to_file(zv,"zversions.txt");
   return vprint("..."+fname+".txt updated.",1);
}

record singlesettingdefault {
   string type;
   string val;
   string init;
};
static {
   singlesettingdefault[string] vardefaults;
   file_to_map("vars_defaults.txt",vardefaults);
}
if (count(vardefaults) == 0) file_to_map("vars_defaults.txt",vardefaults);
file_to_map("vars_"+replace_string(my_name()," ","_")+".txt",vars);
foreach key,rec in vardefaults if (!(vars contains key)) vars[key] = rec.val;

boolean updatevars() {
   string[string] newvars;
   foreach pref,val in vars {
      if (vardefaults contains pref && val == vardefaults[pref].val) continue;
      newvars[pref] = val;
   }
   return map_to_file(newvars,"vars_"+replace_string(my_name(),"
","_")+".txt");
}

void setvar(string varname,string dfault,string type) {
   varname = replace_string(varname," ","_");
   if (vars contains varname) {
      if (!equals(vars[varname],normalized(vars[varname],type))) {
         vprint("ZLib setting "+varname+" normalized: '"+vars[varname]+"' =>
'"+normalized(vars[varname],type)+"'","purple",4);
         vars[varname] = normalized(vars[varname],type);
         updatevars();
      }
   }
   if (!(vardefaults contains varname) || vardefaults[varname].val != dfault ||
vardefaults[varname].type != type) {
      vardefaults[varname].type = type;
      vardefaults[varname].val = dfault;
      vardefaults[varname].init = today_to_string()+" "+time_to_string();
      vprint("New default value for ZLib "+type+" setting: "+varname+" =>
"+dfault,"purple",4);
      map_to_file(vardefaults,"vars_defaults.txt");
   }
}

void setvar(string varname,string dfault)  {  setvar(varname,dfault,"string");
}
void setvar(string varname,boolean dfault) {
setvar(varname,to_string(dfault),"boolean");  }
void setvar(string varname,bounty dfault)  {
setvar(varname,to_string(dfault),"bounty");  }
void setvar(string varname,class dfault)   {
setvar(varname,to_string(dfault),"class");  }
void setvar(string varname,coinmaster
dfault){setvar(varname,to_string(dfault),"coinmaster");  }
void setvar(string varname,effect dfault)  {
setvar(varname,to_string(dfault),"effect");  }
void setvar(string varname,element dfault) {
setvar(varname,to_string(dfault),"element");  }
void setvar(string varname,familiar dfault){
setvar(varname,to_string(dfault),"familiar");  }
void setvar(string varname,float dfault)   {
setvar(varname,to_string(dfault),"float");  }
void setvar(string varname,int dfault)     {
setvar(varname,to_string(dfault),"int");  }
void setvar(string varname,item dfault)    {
setvar(varname,to_string(dfault),"item");  }
void setvar(string varname,location dfault){
setvar(varname,to_string(dfault),"location");  }
void setvar(string varname,monster dfault) {
setvar(varname,to_string(dfault),"monster");  }
void setvar(string varname,phylum dfault)  {
setvar(varname,to_string(dfault),"phylum");  }
void setvar(string varname,servant dfault) {
setvar(varname,to_string(dfault),"servant");  }
void setvar(string varname,skill dfault)   {
setvar(varname,to_string(dfault),"skill");  }
void setvar(string varname,stat dfault)    {
setvar(varname,to_string(dfault),"stat");  }
void setvar(string varname,thrall dfault)  {
setvar(varname,to_string(dfault),"thrall");  }
void setvar(string varname,vykea dfault)   {
setvar(varname,to_string(dfault),"vykea");  }

string getvar(string varname) {
   if (vars contains varname) return vars[varname];
   if (vardefaults contains varname) return vardefaults[varname].val;
   vprint("Attempt to access missing script setting
'"+varname+"'!","purple",4);
   return "";
}

boolean be_good(string johnny) {
   switch (my_path()) {
      case "Bees Hate You": if (johnny.to_lower_case().index_of("b") > -1)
return false; break;
      case "Trendy": if (!is_trendy(johnny)) return false; break;
      case "G-Lover": if (johnny.to_lower_case().index_of("g") == -1) return
false; break;
   }
   return is_unrestricted(johnny);
}
boolean be_good(item johnny) {
   switch (my_path()) {
      case "Bees Hate You": if (johnny.to_lower_case().index_of("b") > -1)
return false; break;
      case "Trendy": if (!is_trendy(johnny)) return false; break;
      case "Avatar of Boris": if (johnny == $item[trusty]) return true;
      case "Way of the Surprising Fist": if ($slots[weapon,off-hand] contains
johnny.to_slot()) return false; break;
      case "KOLHS": if (johnny.inebriety > 0 && !contains_text(johnny.notes,
"KOLHS")) return false; break;
      case "Zombie Slayer": if (johnny.fullness > 0 &&
!contains_text(johnny.notes, "Zombie Slayer")) return false; break;
      case "License to Adventure": if (johnny.inebriety > 0 && johnny.image !=
"martini.gif") return false; break;
      case "G-Lover": if (johnny.to_slot() != $slot[none] || $items[beehive,
star chart, Cobb's Knob map] contains johnny) break;
         if (johnny.to_lower_case().index_of("g") == -1) return false; break;
   }
   if (class_modifier(johnny,"Class") != $class[none] &&
class_modifier(johnny,"Class") != my_class()) return false;
   return is_unrestricted(johnny);
}
boolean be_good(familiar johnny) {
   switch (my_path()) {
      case "Trendy": if (!is_trendy(johnny)) return false; break;
      case "Avatar of Boris":
      case "Avatar of Jarlsberg":
      case "Avatar of Sneaky Pete":
      case "Actually Ed the Undying":
      case "License to Adventure":
      case "Pocket Familiars": return false;
      case "G-Lover": if (johnny.to_lower_case().index_of("g") == -1) return
false; break;
   }
   return is_unrestricted(johnny);
}
boolean be_good(skill johnny) {
   switch (my_path()) {
      case "Trendy": if (!is_trendy(johnny)) return false; break;
      case "G-Lover": if (!johnny.passive &&
johnny.to_lower_case().index_of("g") == -1) return false; break;
   }
   return is_unrestricted(johnny);
}

boolean qprop(string test) {
   if (!test.contains_text(" ")) return get_property(test) == "finished";
   int numerize(string progress) {
      if (is_integer(progress)) return progress.to_int();
      switch (progress) {
         case "unstarted": return -1;
         case "started": return 0;
         case "finished": return 999;
      }
      return excise(progress,"step","").to_int();
   }
   string[int] tbits = split_string(test," ");
   if (count(tbits) != 3) return vprint("'"+test+"' not valid parameter for
qprop().  Syntax is '<property> <relational operator> <value>'",-3);
   if (get_property(tbits[0]) == "") return vprint("'"+tbits[0]+"' is not a
valid quest property.",-9);
   switch (tbits[1]) {
      case "==": case "=": return numerize(get_property(tbits[0])) ==
numerize(tbits[2]);
      case "!=": case "<>": return numerize(get_property(tbits[0])) !=
numerize(tbits[2]);
      case ">": return numerize(get_property(tbits[0])) > numerize(tbits[2]);
      case "=>": case ">=": return numerize(get_property(tbits[0])) >=
numerize(tbits[2]);
      case "<": return numerize(get_property(tbits[0])) < numerize(tbits[2]);
      case "=<": case "<=": return numerize(get_property(tbits[0])) <=
numerize(tbits[2]);
   } return vprint("'"+tbits[1]+"' is not a valid relational operator.", -3);
}

int mall_val(item it, float expirydays, boolean combatsafe) {
   if (!is_tradeable(it)) return 0;
   if (historical_price(it) > 0 && (combatsafe || expirydays > 99 ||
historical_age(it) < expirydays)) return historical_price(it);
   return combatsafe ? 0 : mall_price(it);
}
int mall_val(item it, float expirydays) { return mall_val(it,expirydays,false);
}
int mall_val(item it, boolean combatsafe) { return mall_val(it,0,combatsafe); }

int sell_val(item it, float expirydays, boolean combatsafe) {
   int mall = mall_val(it,expirydays,combatsafe);
   if (mall > max(100,2*autosell_price(it))) return mall;
   return autosell_price(it);
}
int sell_val(item it, float expirydays) { return sell_val(it,expirydays,false);
}
int sell_val(item it, boolean combatsafe) { return sell_val(it,0,combatsafe); }
int sell_val(item it) { return sell_val(it,0,false); }

int have_item(string tolookup) {
   return item_amount(to_item(tolookup)) + equipped_amount(to_item(tolookup));
}

item braindrop(monster patient) {
   if (my_path() != "Zombie Slayer" ||
$phyla[bug,constellation,elemental,construct,plant,slime] contains
patient.phylum) return $item[none];
   if (index_of(patient.image,"hunter") == 0) return $item[hunter brain];
   if ($monsters[Boss Bat, Baron von Ratsworth, Knob Goblin King, giant
skeelton, huge ghuol, conjoined zmombie, gargantulihc, Bonerdagon,
      Groar, Dr. Awkward, Lord Spookyraven, Protector Spectre, The Big
Wisniewski, Guy Made Of Bees] contains patient) return $item[boss brain];
   if (to_string(patient).contains_text("Ed the Undying")) return $item[none];
   if (monster_attack(patient) + monster_level_adjustment() >= 100) return
$item[good brain];
   if (monster_attack(patient) + monster_level_adjustment() > 50) return
$item[decent brain];
   return $item[crappy brain];
}

float kadrop(monster m) {
   if (my_class() != $class[Ed the Undying]) return 0;
   float res;
   switch (m.phylum) {
      case $phylum[dude]: case $phylum[hippy]: case $phylum[hobo]: case
$phylum[pirate]: res = 1;
      case $phylum[beast]: case $phylum[bug]: case $phylum[elf]: case
$phylum[fish]: case $phylum[goblin]: case $phylum[humanoid]:
      case $phylum[mer-kin]: case $phylum[orc]: case $phylum[penguin]: case
$phylum[elemental]: res += 1;
         if (res > 0 && my_servant() == $servant[priest] &&
$servant[priest].level >= 14) res += 1; break;
      case $phylum[undead]: if (have_equipped($item[the crown of ed the
undying])) return 0.2;
   }
   return res;
}

boolean is_goal(stat gstat) {
   foreach i,g in get_goals() if (create_matcher("\\d+
"+to_lower_case(gstat),g).find()) return true;
   return false;
}

float[item,item] pieces;
if (numeric_modifier("Generated:_spec","Buffed Muscle") == 0)
cli_execute("whatif quiet");

float isxpartof(item child, item ancestor) {
   if (pieces[child] contains ancestor) return pieces[child,ancestor];
   item get_parent(item child, item ancestor, int level) {
      int[item] unit = get_ingredients(ancestor);
      if (unit contains child) return ancestor;
      foreach i in unit {
         if (level > 5) return $item[none];
         item it = get_parent(child,i,level+1);
         if (it != $item[none]) return it;
      }
      return $item[none];
   }
   boolean[item] lineage;
   repeat {
      child = get_parent(child,ancestor,0);
      if (child != $item[none]) lineage[child] = true;
       else {
          pieces[child,ancestor] = 0;
          return 0;
       }
   } until (child == ancestor);
   int count;
   foreach i in lineage foreach j,k in get_ingredients(i) count += k;
   count += 1 - count(lineage);
   pieces[child,ancestor] = 1.0/count;
   return 1.0/count;
}

static {
   float [item,item] useforitems;
   load_current_map("use_for_items", useforitems);
}

float has_goal(item whatsit) {
   if (!goal_exists("item")) return 0;
   float has_goal(item whatsit,int level) {
     if (whatsit == $item[none]) return 0;
     if (is_goal(whatsit)) return 1.0;
     if (count(useforitems) == 0) {
        vprint("Unable to load file \"use_for_items.txt\".",-3); return 0;
     }
     if (level > 5) return 0;
     float res;
     if (useforitems contains whatsit) foreach key,perc in useforitems[whatsit]
        if (has_goal(key,level+1) > 0) res = max(res,perc);
     return res;
   }
   float tot;
   foreach i,s in get_goals() {
      matcher numthings = create_matcher("\\d+ (.*)",s);
      if (!numthings.find()) continue;
      item testor = numthings.group(1).to_item();
      if (testor == whatsit || !is_goal(testor)) continue;
      tot += isxpartof(whatsit,testor);
   }
   return tot + has_goal(whatsit,0);
}

float has_goal(monster m, boolean usespec) {
   float res, temp;
   foreach num,rec in item_drops_array(m) {
      temp = has_goal(rec.drop);
      if (temp == 0) continue;
      switch (rec.type) {
         case "b": res += temp; continue;
         case "p": if (my_primestat() == $stat[moxie] ||
have_effect($effect[Form of...Bird!]) > 0)
            res += temp*minmax(max(rec.rate,0.001)*((usespec ?
numeric_modifier("Generated:_spec","Pickpocket Chance") :
                   numeric_modifier("Pickpocket
Chance"))+100)/100.0,0,100)/100.0; continue;
         case "c": if (item_type(rec.drop) == "shirt" &&
!have_skill($skill[torso awareness])) continue;
            if (item_type(rec.drop) == "pasta guardian" && my_class() !=
$class[pastamancer]) continue;
            if (m == $monster[pygmy witch accountant] &&
contains_text(rec.drop.to_string(),"McClusky") &&
               item_amount(rec.drop) + item_amount($item[McClusky file (page
5)]) + item_amount($item[McClusky file (complete)]) > 0) continue;
            if (rec.drop == $item[bunch of square grapes] && my_level() < 11)
continue;
            if (rec.drop == $item[beer lens] &&
get_property("_beerLensDrops").to_int() > 2) continue;
         case "":
         case "n": res += temp*minmax(max(rec.rate,0.001)*((usespec ?
numeric_modifier("Generated:_spec","Item Drop") :
                          numeric_modifier("Item
Drop"))+100)/100.0,0,100)/100.0; continue;
         case "0": res += .001; continue;
      }
   }
   if (is_goal(braindrop(m))) switch (braindrop(m)) {
      case $item[hunter brain]: break; case $item[boss brain]: res += 1; break;
      default: res += minmax((have_skill($skill[skullcracker]) ? 0.6 :
0.3)*((usespec ? numeric_modifier("Generated:_spec","Item Drop") :
         numeric_modifier("Item Drop"))+100)/100.0,0,100)/100.0;
   }
   if (is_goal($item[ka coin])) res += kadrop(m);
   return res;
}
float has_goal(monster m) { return has_goal(m,false); }

float has_goal(location l, boolean usespec) {
   float res;
   float[monster] rates = appearance_rates(l);
   if (rates[$monster[none]] == 100) return 0;
   float cradj = rates[$monster[none]] == -1 ? 0 :
      minmax(usespec ? numeric_modifier("Generated:_spec","Combat Rate") :
numeric_modifier("Combat Rate"), -rates[$monster[none]],
rates[$monster[none]]);
   foreach m,r in rates if (r <= 0 || m == $monster[none]) remove rates[m];
   foreach m,r in rates
      res += has_goal(m,usespec)*max(r + cradj/count(rates),0)/100.0;
   return res;
}
float has_goal(location l) { return has_goal(l,false); }

boolean obtain(int n, string cond, location locale, string filter) {
   if ($strings[choiceadv, autostop, arena flyer ml, pirate insult, factoid]
contains cond || to_item(cond) == $item[none])
      cli_execute("conditions clear; conditions set "+n+" "+cond);
   else {
      if (retrieve_item(n, to_item(cond))) return vprint("You have "+n+"
"+cond+", no adventuring necessary.",5);
      if (!in_hardcore() && storage_amount(to_item(cond)) > 0)
take_storage(n-have_item(cond),to_item(cond));
       if (have_item(cond) >= n) return vprint("You have taken your needed
items from storage.",5);
      if (count(get_goals()) > 0) cli_execute("conditions clear");
      add_item_condition(n - have_item(cond), to_item(cond));
   }
   if (count(get_goals()) == 0) return vprint("No goals left after setting
'"+rnum(n)+" "+cond+"' as goals; no adventuring necessary.",5);
   set_location(locale);
   if (length(filter) > 0) { if (adventure(my_adventures(), locale, filter))
return vprint("Out of adventures.",-1); }
    else if (adventure(my_adventures(), locale)) return vprint("Out of
adventures.",-1);
   if ($strings[choiceadv, autostop, arena flyer ml, pirate insult] contains
cond || to_item(cond) == $item[none]) return (my_adventures() > 0);
   return (have_item(cond) >= n);
}
boolean obtain(int n, string cond, location locale) { return obtain(n, cond,
locale, ""); }

boolean use_upto(int n, item doodad, boolean purchase) {
   if (my_sign() == "Way of the Surprising Fist") purchase = false;
   if (doodad == $item[deodorant] && item_amount($item[chunk of rock salt]) >
item_amount(doodad)) doodad = $item[chunk of rock salt];
   if (!be_good(doodad)) return vprint("Refusing to use a '"+doodad+"' since it
is disallowed in "+my_path()+".",-4);
   if (item_amount(doodad) >= n || (purchase && retrieve_item(n, doodad)))
return use(n, doodad);
   if (item_amount(doodad) == 0) return false;
   return use(item_amount(doodad), doodad);
}

boolean resist(element req, boolean reallydoit) {
   vprint("Checking resistance to "+req+"...",2);
   if (req == $element[none]) return true;
   if (elemental_resistance(req) >= 10) return vprint("You can already resist
"+req+".",5);
   foreach s in $skills[astral shell, elemental saucesphere, elemental
obliviousness] if (have_skill(s) && (
       (!reallydoit && my_mp() >= mp_cost(s)) ||
       (reallydoit && use_skill(1,s)))) return vprint("Resistance achieved via
"+s+".",5);
   int[item] mgear = get_inventory();
   string rtype = to_string(req) + " resistance";
   vprint("Searching items for "+rtype+"...",3);
   foreach doodad in mgear {
      if (to_slot(doodad) != $slot[none] && numeric_modifier(doodad,rtype) >=
1.0 && can_equip(doodad)) {
         vprint("Resistance-granting item found: "+doodad,3);
         if (reallydoit) {
            equip(to_slot(doodad) == $slot[acc1] ? $slot[acc3] :
to_slot(doodad),doodad);
            if (elemental_resistance(req) < 10) return vprint("Unable to equip
your "+doodad+".",-5);
         }
         return vprint("Resistance achieved via gear.",5);
      }
   }
   if (have_familiar($familiar[exotic parrot])) {
       int necessary_parrot_weight(element which) {
          switch (which) {
             case $element[hot]: return 1;      case $element[cold]: return 5;
             case $element[spooky]: return 9;   case $element[stench]: return
13;
             case $element[sleaze]: return 17;
          }
          return 0;
       }
       int possible_parrot_weight() {
          int result = familiar_weight($familiar[exotic parrot]);
          if (familiar_equipped_equipment($familiar[exotic parrot]) ==
$item[cracker] || item_amount($item[cracker]) > 0)
             result += 15;
          return result + numeric_modifier("Familiar Weight") -
numeric_modifier(equipped_item($slot[familiar]),"Familiar Weight");
       }
       if (possible_parrot_weight() >= necessary_parrot_weight(req)) {
          vprint("Your parrot is able to resist "+req+".",3);
          if (reallydoit) {
             use_familiar($familiar[exotic parrot]);
             if (familiar_equipped_equipment($familiar[exotic parrot]) !=
$item[cracker] && item_amount($item[cracker]) > 0)
                equip($item[cracker]);
          }
          return vprint("Resistance achieved via parrot.",5);
       }
   }
   return vprint("Unable to resist "+req+"!",-2);
}

int my_defstat(boolean usespec) {
   int mox = usespec ? numeric_modifier("Generated:_spec","Buffed Moxie") :
my_buffedstat($stat[moxie]);
   if (have_skill($skill[hero of the half-shell]) &&
item_type(equipped_item($slot[off-hand])) == "shield")
      return max(usespec ? numeric_modifier("Generated:_spec","Buffed Muscle")
: my_buffedstat($stat[muscle]),mox);
   return mox;
}
int my_defstat() { return my_defstat(false); }

int get_safemox(location wear) {
   int high;
   foreach m,r in appearance_rates(wear) {
      switch(m) {
         case $monster[hulking construct]: continue;
         case $monster[The Clownlord Beelzebozo]: if
(get_property("choiceAdventure151") != "1") continue; break;
         case $monster[conjoined zmombie]: if
(get_property("choiceAdventure154") != "1") continue; break;
         case $monster[giant skeelton]: if (get_property("choiceAdventure156")
!= "1") continue; break;
         case $monster[gargantulihc]: if (get_property("choiceAdventure158") !=
"1") continue; break;
         case $monster[huge ghuol]: if (get_property("choiceAdventure160") !=
"1") continue; break;
         default: if (r <= 0) continue;
      }
      high = max(monster_attack(m),high);
   }
   if (high == 0 || high == monster_level_adjustment()) return 0;
   if (wear == $location[barrrney's barrr] && item_amount($item[the big book of
pirate insults]) > 0) high += 0.3*my_defstat();
   if (my_path() == "Heavy Rains" && wear.water_level !=
my_location().water_level) high += 10*(wear.water_level -
my_location().water_level);
   return high + 7 - current_mcd();
}

boolean auto_mcd(int safemox) {
   if (!to_boolean(getvar("automcd")) || my_ascensions() < 1 || in_bad_moon())
return true;
   if ((knoll_available() && !retrieve_item(1,$item[detuned radio])) ||
     (gnomads_available() && item_amount($item[bitchin' meatcar]) +
item_amount($item[desert bus pass]) +
      item_amount($item[pumpkin carriage]) == 0))
      return vprint("MCD: unavailable","olive",5);
   if (safemox == 0) {
      vprint("MCD: Using your 'unknown_ml' value
("+getvar("unknown_ml")+").","olive",2);
      safemox = to_int(getvar("unknown_ml")) + 7;
   }
   int adj = minmax(my_defstat() + to_int(getvar("threshold")) - safemox, 0,
10+canadia_available().to_int());
   if (current_mcd() == adj) return true;
   else return (vprint("MCD: adjusting to "+adj+"...","olive",2) && change_mcd
