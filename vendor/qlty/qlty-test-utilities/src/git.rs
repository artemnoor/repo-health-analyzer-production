use git2::{Repository, RepositoryInitOptions};
use std::fs;
use std::path::Path;
use tempfile::TempDir;

pub fn init(path: &Path) -> Repository {
    let mut opts = RepositoryInitOptions::new();
    opts.initial_head("main");
    let repo = Repository::init_opts(path, &opts).unwrap();
    {
        let mut config = repo.config().unwrap();
        config.set_str("user.name", "name").unwrap();
        config.set_str("user.email", "email").unwrap();
        let mut index = repo.index().unwrap();
        index
            .add_all(["."].iter(), git2::IndexAddOption::DEFAULT, None)
            .unwrap();
        index.write().unwrap();
        let id = index.write_tree().unwrap();
        let tree = repo.find_tree(id).unwrap();
        let sig = repo.signature().unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "initial\n\nbody", &tree, &[])
            .unwrap();
    }
    repo
}

pub fn empty_repo() -> (TempDir, Repository) {
    let td = create_temp_dir();
    let repo = init(td.path());
    (td, repo)
}

pub fn sample_repo() -> (TempDir, Repository) {
    let td = build_sample_project();
    let repo = init(td.path());
    (td, repo)
}

pub fn sample_repo_feature_branch() -> (TempDir, Repository) {
    // Start from the sample_repo state
    let (td, repo) = sample_repo();

    // Use a nested block to limit the scope of feature_branch
    {
        // 1. Checkout to a new branch called "feature".
        let feature_branch = repo
            .branch(
                "feature",
                &repo.head().unwrap().peel_to_commit().unwrap(),
                false,
            )
            .unwrap();
        repo.set_head(&format!(
            "refs/heads/{}",
            feature_branch.name().unwrap().unwrap()
        ))
        .unwrap();
        repo.checkout_head(Some(git2::build::CheckoutBuilder::default().force()))
            .unwrap();

        // 2. Make the desired changes.
        fs::write(
            td.path().join("lib/hello.rb"),
            "class Hello; end\nputs 'new feature'",
        )
        .unwrap();
        fs::write(td.path().join("greetings.rb"), "puts 'new feature'").unwrap();
        // new file
        fs::write(td.path().join("new_feature.rb"), "puts 'new feature'").unwrap();

        // 3. Commit the changes to the "feature" branch.
        let mut index = repo.index().unwrap();
        index
            .add_all(["."].iter(), git2::IndexAddOption::DEFAULT, None)
            .unwrap();
        index.write().unwrap();

        let id = index.write_tree().unwrap();
        let tree = repo.find_tree(id).unwrap();
        let sig = repo.signature().unwrap();
        let head_commit = repo.head().unwrap().peel_to_commit().unwrap();
        let parents = vec![&head_commit];

        repo.commit(
            Some("HEAD"),
            &sig,
            &sig,
            "Added new feature\n\nDetailed description",
            &tree,
            &parents,
        )
        .unwrap();
    } // feature_branch is dropped here, releasing its borrow on repo

    (td, repo)
}

pub fn dirty_repo() -> (TempDir, Repository) {
    let td = build_sample_project();
    let path = td.path();
    let repo = init(path);

    fs::write(path.join("lib/hello.rb"), "class Hello; end\nputs 'dirty'").unwrap();
    fs::write(path.join("greetings.rb"), "puts 'dirty'").unwrap();
    fs::write(path.join("new.rb"), "puts 'dirty'").unwrap();

    let mut index = repo.index().unwrap();
    index
        .add_all(["lib/hello.rb"].iter(), git2::IndexAddOption::DEFAULT, None)
        .unwrap();
    index.write().unwrap();

    // Changes to be committed:
    // modified:   lib/hello.rb

    // Changes not staged for commit:
    // modified:   greetings.rb

    // Untracked files:
    // new.rb

    (td, repo)
}

pub fn create_temp_dir() -> TempDir {
    TempDir::new_in(".").unwrap()
}

pub fn build_sample_project() -> TempDir {
    // lib
    // ├── hello.rb
    // ├── ignored.rb
    // └── tasks
    //    ├── ignored_tasks
    //    │  └── ignored.rb
    //    │  └── any.rb
    //    ├── ops
    //    │  ├── deploy.rb
    //    │  └── setup.rb
    //    └── ignored.rb
    //    └── some.rb
    // ignored.rb
    // greetings.rb
    // README.md
    // .gitignore
    let td = create_temp_dir();
    let path = td.path();

    let dir_structure = [
        "lib",
        "lib/tasks",
        "lib/tasks/ignored_tasks",
        "lib/tasks/ops",
    ];

    for dir in &dir_structure {
        fs::create_dir_all(path.join(dir)).unwrap();
    }

    let file_contents = [
        ("lib/hello.rb", "class Hello; end"),
        ("lib/ignored.rb", "puts 'ignored'"),
        ("lib/tasks/ignored_tasks/ignored.rb", "puts 'ignored'"),
        ("lib/tasks/ignored_tasks/any.rb", "puts 'any'"),
        ("lib/tasks/ops/deploy.rb", "puts 'deploy'"),
        ("lib/tasks/ops/setup.rb", "puts 'setup'"),
        ("lib/tasks/some.rb", "puts 'some'"),
        ("lib/tasks/ignored.rb", "puts 'some'"),
        ("greetings.rb", "puts 'greetings'"),
        ("ignored.rb", "puts 'ignored'"),
        ("README.md", "# Hello, world!"),
        (".gitignore", "ignored.*\nlib/tasks/ignored_tasks"),
    ];

    for (file_path, content) in &file_contents {
        fs::write(path.join(file_path), content).unwrap();
    }

    td
}
