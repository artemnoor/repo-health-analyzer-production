fn f0() {}

fn f1(dog: i32, cat: String) {}

fn f2(a: i32, b: String, c: f64, d: bool, e: Vec<i32>, f: Option<&str>) {}

fn f3() {
    // Function calls don't count, only function definitions
    let path = format!(
        "/repos/{}/comparisons/{}...{}/coverage",
        repo_id, comparison_commit_sha, commit_sha
    );
}
