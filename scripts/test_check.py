import json
from pathlib import Path
import tempfile
import unittest

from check import diagnostics, folder_sizes, load_config, parse_exceptions, ratchet, tighten
from rust import Size, measure


class RustCountingTests(unittest.TestCase):
    def test_inline_tests_ignore_literals_comments_lifetimes_and_nested_modules(self):
        source = '''fn production<'a>(v: &'a str) {}
#[cfg(test)]
mod tests {
    const RAW: &str = r###"}
#[cfg(test)]
mod fake {"###;
    /* } /* { */ } */
    const CHAR: char = '}';
    const ESCAPE: char = '\\u{7d}';
    const STRING: &str = "} \\" {";
    #[cfg(test)]
    mod nested { fn helper() {} }
}
fn after() {}
'''
        size = measure("src/lib.rs", source)
        self.assertEqual(size.source, 2)
        self.assertEqual(size.tests, 12)

    def test_attributes_and_external_test_modules_exclude_only_the_test_item(self):
        source = '''#[cfg(test)]
#[path = "suite.rs"]
mod tests;
pub fn production() {}
#[cfg(test)]
fn helper() { let _ = br#"} {"#; }
pub fn more() {}
'''
        size = measure("src/main.rs", source)
        self.assertEqual((size.source, size.tests), (2, 3))

    def test_test_paths_and_individual_inline_module_limits(self):
        for path in ["src/tests.rs", "src/request_tests.rs", "tests/helpers.rs"]:
            self.assertEqual(measure(path, "a\nb\n").tests, 2)
            self.assertEqual(measure(path, "a\nb\n").source, 0)
        size = measure("src/lib.rs", "#[cfg(test)]\nmod a {}\n#[cfg(test)]\nmod b {}\n")
        self.assertEqual((size.source, size.tests), (0, 2))

    def test_cfg_text_in_a_production_raw_string_does_not_hide_source(self):
        source = 'const FIXTURE: &str = r#"\n#[cfg(test)]\nmod hidden {}\n"#;\nfn next() {}\n'
        self.assertEqual((measure("lib.rs", source).source, measure("lib.rs", source).tests), (5, 0))

    def test_platform_gated_tests_are_excluded_but_optional_production_code_is_not(self):
        source = '''#[cfg(all(test, unix))]
mod tests { fn helper() {} }
#[cfg(any(test, feature = "production"))]
fn production() {}
#[cfg(not(test))]
fn release_only() {}
'''
        size = measure("lib.rs", source)
        self.assertEqual((size.source, size.tests), (4, 2))


class GuardrailTests(unittest.TestCase):
    def test_config_merges_default_limits_and_rejects_invalid_limit_relationships(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.json"
            config_file.write_text(json.dumps({"paths": ["src"], "limits": {"source": 700}}))
            config = load_config(root, "config.json")
            self.assertEqual(config["paths"], ["src"])
            self.assertEqual(config["limits"]["source"], 700)
            config_file.write_text(json.dumps({"limits": {"source": 1600}}))
            with self.assertRaises(ValueError):
                load_config(root, "config.json")

    def test_source_and_test_caps_and_existing_ceilings(self):
        sizes = {("source", "large.rs"): 1501, ("source", "medium.rs"): 801, ("tests", "tests.rs"): 1001}
        self.assertEqual([row[0] for row in diagnostics(sizes, {})], ["error", "error", "error"])
        exceptions = {("source", "large.rs"): 1600, ("tests", "tests.rs"): 1100}
        self.assertEqual([row[0] for row in diagnostics(sizes, exceptions)], ["warning", "error", "warning"])
        sizes[("source", "large.rs")] += 100
        self.assertEqual(diagnostics(sizes, exceptions)[0][0], "error")

    def test_over_limit_sources_allow_only_unchanged_or_shrinking_legacy_files(self):
        legacy = {("source", "legacy.rs"): 900}
        self.assertEqual(diagnostics(legacy, {}, {"legacy.rs": 900}, set())[0][0], "warning")
        self.assertEqual(diagnostics(legacy, {}, {"legacy.rs": 900}, {"legacy.rs"})[0][0], "error")
        self.assertEqual(diagnostics({("source", "legacy.rs"): 850}, {}, {"legacy.rs": 900}, {"legacy.rs"})[0][0], "warning")
        self.assertEqual(diagnostics({("source", "legacy.rs"): 901}, {}, {"legacy.rs": 900}, {"legacy.rs"})[0][0], "error")

    def test_exception_ceilings_only_decrease(self):
        previous = parse_exceptions("# baseline\nsource big.rs 1600\ntests tests.rs 1100\n")
        self.assertEqual(ratchet(previous, {("source", "big.rs"): 1500}), [])
        self.assertEqual(len(ratchet(previous, {("source", "big.rs"): 1601})), 1)
        self.assertEqual(len(ratchet(previous, {("source", "new.rs"): 1600})), 1)
        self.assertEqual(tighten(previous, {("source", "big.rs"): 1400}, {"source": 800, "source_hard": 1500, "tests": 1000, "folder_soft": 40, "folder_hard": 60}), {("source", "big.rs"): 1400})
        with self.assertRaises(ValueError):
            parse_exceptions("source a.rs 1600\nsource a.rs 1700\n")

    def test_capability_families_and_folder_breadth_exclude_tests_and_bins(self):
        paths = ["crates/a/src/review.rs", "crates/a/src/review_files.rs", "crates/a/src/review_threads.rs",
                 "crates/a/src/review_tests.rs", "crates/a/src/bin/review_run.rs"]
        self.assertEqual(folder_sizes(paths), {("family", "crates/a/src/review_*"): 2})
        paths = ["src/editor/mod.rs", "src/editor_input.rs", "src/editor_scroll.rs"]
        self.assertIn(("family", "src/editor_*"), folder_sizes(paths))
        paths = [f"src/file{i}.rs" for i in range(61)]
        self.assertEqual(folder_sizes(paths), {("folder", "src"): 61})
        self.assertEqual(diagnostics(folder_sizes(paths), {})[0][0], "error")


if __name__ == "__main__":
    unittest.main()
