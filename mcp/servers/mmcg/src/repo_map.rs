//! Bounded question-specific navigation. Source/index bindings are checked by its caller.

use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};

pub const MAX_SYMBOLS: usize = 20000;
pub const MAX_GRAPH_EDGES: usize = 100000;
pub const NAVIGATION_INSTRUCTIONS: &str =
    "Read relevant locations directly, then follow calls or search for missing locations.\n\
    Track ranges already read; extend with uncovered gaps. Read source to support claims.\n";

#[derive(Clone)]
pub struct Symbol {
    pub file: String,
    pub name: String,
    pub kind: String,
    pub line: u32,
    pub signature: Option<String>,
}

pub struct Input {
    pub question: String,
    pub source_sha256: String,
    pub budget_bytes: usize,
    pub symbols: Vec<Symbol>,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Location {
    pub file: String,
    pub line: u32,
    pub name: String,
    pub kind: String,
}

impl From<&Symbol> for Location {
    fn from(symbol: &Symbol) -> Self {
        Self {
            file: symbol.file.clone(),
            line: symbol.line,
            name: symbol.name.clone(),
            kind: symbol.kind.clone(),
        }
    }
}

#[derive(Default)]
pub struct Graph {
    pub edges: Vec<(Location, Location)>,
    pub scanned_edges: usize,
    pub omitted_targets: usize,
    pub overflow: bool,
}

#[derive(Serialize)]
pub struct GraphSummary {
    pub scanned_edges: usize,
    pub omitted_targets: usize,
    pub usable_edges: usize,
    pub iterations: usize,
    pub fallback: Option<&'static str>,
}

#[derive(Serialize)]
pub struct Output {
    pub schema_version: u32,
    pub algorithm: &'static str,
    pub source_sha256: String,
    pub budget_bytes: usize,
    pub payload_bytes: usize,
    pub selected: usize,
    pub candidates: usize,
    pub relevant_candidates: usize,
    pub truncated: bool,
    pub payload: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub graph: Option<GraphSummary>,
}

impl Output {
    /// Keep the same selected locations and reservation as the combined header.
    pub fn map_only(mut self) -> Self {
        self.payload = self.payload.replacen(NAVIGATION_INSTRUCTIONS, "", 1);
        self.payload_bytes = self.payload.len();
        self
    }

    pub fn instructions_only(mut self) -> Self {
        self.payload = NAVIGATION_INSTRUCTIONS.into();
        self.payload_bytes = self.payload.len();
        self.selected = 0;
        self.truncated = self.candidates > 0;
        self
    }
}

fn words(text: &str) -> BTreeSet<String> {
    let mut expanded = String::new();
    let mut previous_lower = false;
    for c in text.chars() {
        if previous_lower && c.is_uppercase() {
            expanded.push(' ');
        }
        expanded.push(c);
        previous_lower = c.is_lowercase();
    }
    expanded
        .split(|c: char| !c.is_alphanumeric())
        .filter(|word| word.chars().count() >= 4)
        .map(str::to_lowercase)
        .map(|word| {
            if word.len() > 6 && word.ends_with("ing") {
                word[..word.len() - 3].to_string()
            } else if word.len() > 5 && word.ends_with("ed") {
                word[..word.len() - 2].to_string()
            } else if word.len() > 4 && word.ends_with('s') && !word.ends_with("ss") {
                word[..word.len() - 1].to_string()
            } else {
                word
            }
        })
        .collect()
}

fn single_line(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn file_terms(file: &str) -> BTreeSet<String> {
    words(file.rsplit('/').next().unwrap_or(file))
}

fn location_order(a: &Symbol, b: &Symbol) -> std::cmp::Ordering {
    a.file
        .cmp(&b.file)
        .then(a.line.cmp(&b.line))
        .then(a.name.cmp(&b.name))
        .then(a.kind.cmp(&b.kind))
        .then(a.signature.cmp(&b.signature))
}

pub fn build(input: Input) -> Result<Output, String> {
    build_ranked(input, None)
}

pub fn build_graph(input: Input, graph: Graph) -> Result<Output, String> {
    build_ranked(input, Some(graph))
}

fn eligible(row: &Symbol) -> bool {
    row.kind != "module"
        && row.kind != "impl"
        && !row.signature.as_deref().unwrap_or("").contains("#[test]")
}

fn graph_scores(rows: &[Symbol], lexical: &[f64], graph: Graph) -> (Vec<f64>, GraphSummary) {
    let mut summary = GraphSummary {
        scanned_edges: graph.scanned_edges,
        omitted_targets: graph.omitted_targets,
        usable_edges: 0,
        iterations: 0,
        fallback: None,
    };
    let total: f64 = lexical.iter().sum();
    if graph.overflow || graph.edges.len() > MAX_GRAPH_EDGES || total == 0.0 {
        summary.fallback = Some(if total == 0.0 {
            "no_seeds"
        } else {
            "edge_limit"
        });
        return (lexical.to_vec(), summary);
    }
    let mut locations: BTreeMap<Location, Vec<usize>> = BTreeMap::new();
    for (index, row) in rows.iter().enumerate().filter(|(_, row)| eligible(row)) {
        locations
            .entry(Location::from(row))
            .or_default()
            .push(index);
    }
    let mut adjacency = vec![BTreeSet::new(); rows.len()];
    for (from, to) in graph.edges {
        if let (Some(from), Some(to)) = (locations.get(&from), locations.get(&to)) {
            if from.len() == 1 && to.len() == 1 && from[0] != to[0] {
                adjacency[from[0]].insert(to[0]);
                adjacency[to[0]].insert(from[0]);
            }
        }
    }
    summary.usable_edges = adjacency.iter().map(BTreeSet::len).sum::<usize>() / 2;
    if summary.usable_edges == 0 {
        summary.fallback = Some("no_usable_edges");
        return (lexical.to_vec(), summary);
    }
    let seeds: Vec<_> = lexical.iter().map(|score| score / total).collect();
    let mut rank = seeds.clone();
    // Fixed iterations and sorted adjacency make selection independent of edge insertion order.
    for _ in 0..24 {
        let dangling: f64 = rank
            .iter()
            .zip(&adjacency)
            .filter(|(_, neighbors)| neighbors.is_empty())
            .map(|(rank, _)| rank)
            .sum();
        let mut next: Vec<_> = seeds
            .iter()
            .map(|seed| (0.15 + 0.85 * dangling) * seed)
            .collect();
        for (from, neighbors) in adjacency.iter().enumerate() {
            if !neighbors.is_empty() {
                let share = 0.85 * rank[from] / neighbors.len() as f64;
                for &to in neighbors {
                    next[to] += share;
                }
            }
        }
        rank = next;
    }
    summary.iterations = 24;
    (rank, summary)
}

fn build_ranked(input: Input, graph: Option<Graph>) -> Result<Output, String> {
    if !(512..=16384).contains(&input.budget_bytes)
        || input.symbols.len() > MAX_SYMBOLS
        || input.question.len() > 16384
        || input.source_sha256.len() != 64
        || !input.source_sha256.bytes().all(|c| c.is_ascii_hexdigit())
    {
        return Err("invalid input bounds or source digest".into());
    }
    let terms = words(&input.question);
    let focus = words(input.question.split(['.', '?', '!']).next().unwrap_or(""));
    let mut rows = input.symbols;
    for row in &rows {
        if row.file.is_empty()
            || row.line == 0
            || row.file.starts_with('/')
            || row.file.split('/').any(|p| p == ".." || p.starts_with('.'))
            || row.file.contains('\\')
            || row.file.chars().any(char::is_control)
        {
            return Err("invalid indexed source location".into());
        }
    }
    rows.sort_by(location_order);
    rows.dedup_by(|a, b| {
        a.file == b.file
            && a.line == b.line
            && a.name == b.name
            && a.kind == b.kind
            && a.signature == b.signature
    });
    let candidates = rows.len();
    // Count files rather than definitions so large helper modules do not dominate.
    let mut vocabulary: BTreeMap<&str, BTreeSet<String>> = BTreeMap::new();
    for row in &rows {
        if eligible(row) {
            let entry = vocabulary
                .entry(&row.file)
                .or_insert_with(|| file_terms(&row.file));
            entry.extend(words(&row.name));
        }
    }
    let term_weight = |term: &String| {
        let frequency = vocabulary.values().filter(|v| v.contains(term)).count();
        (1024 / (1 + frequency)) * if focus.contains(term) { 3 } else { 1 }
    };
    let lexical_score = |row: &Symbol| {
        let name = words(&row.name);
        let file = file_terms(&row.file);
        let hits: BTreeSet<_> = terms
            .intersection(&name)
            .chain(focus.intersection(&file))
            .collect();
        let weight = terms.intersection(&name).map(&term_weight).sum::<usize>()
            + focus.intersection(&file).map(&term_weight).sum::<usize>() * 3;
        // Several task terms together are stronger navigation hints than one rare adjective.
        weight * hits.len() * hits.len()
    };
    let lexical: Vec<_> = rows
        .iter()
        .map(|row| {
            if eligible(row) {
                lexical_score(row) as f64
            } else {
                0.0
            }
        })
        .collect();
    let (scores, graph) = match graph {
        Some(graph) => {
            let (scores, summary) = graph_scores(&rows, &lexical, graph);
            (scores, Some(summary))
        }
        None => (lexical, None),
    };
    let score = |row: &Symbol| {
        scores[rows
            .binary_search_by(|candidate| location_order(candidate, row))
            .unwrap()]
    };
    let mut files: BTreeMap<&str, Vec<&Symbol>> = BTreeMap::new();
    for row in &rows {
        if eligible(row) && score(row) > 0.0 {
            files.entry(&row.file).or_default().push(row);
        }
    }
    let relevant_candidates = files.values().map(Vec::len).sum();
    for symbols in files.values_mut() {
        symbols.sort_by(|a, b| score(b).total_cmp(&score(a)).then(location_order(a, b)));
        let best = score(symbols[0]);
        symbols.retain(|row| score(row) * 3.0 >= best);
    }
    let mut files: Vec<_> = files.into_iter().collect();
    files.sort_by(|a, b| score(b.1[0]).total_cmp(&score(a.1[0])).then(a.0.cmp(b.0)));
    if let Some((_, symbols)) = files.first() {
        let best = score(symbols[0]);
        files.retain(|(_, symbols)| score(symbols[0]) * 2.0 >= best);
    }
    let mut payload = format!(
        "Repository map: partial definition locations from frozen source {digest}.\n\
         {NAVIGATION_INSTRUCTIONS}\
         This shortlist is navigation metadata, not behavioral evidence or complete coverage.\n",
        digest = input.source_sha256
    );
    let mut selected = 0;
    // A shortlist leaves room for source evidence instead of filling the whole budget.
    for (file, symbols) in files.into_iter().take(3) {
        let mut section = format!("{file}\n");
        let mut section_selected = 0;
        for row in symbols.into_iter().take(3) {
            let line = format!(
                "  :{} {} {}\n",
                row.line,
                single_line(&row.kind),
                single_line(&row.name)
            );
            if payload.len() + section.len() + line.len() <= input.budget_bytes {
                section.push_str(&line);
                section_selected += 1;
            }
        }
        if section_selected > 0 {
            payload.push_str(&section);
            selected += section_selected;
        }
    }
    Ok(Output {
        schema_version: 1,
        algorithm: if graph.is_some() {
            "personalized_graph_v1"
        } else {
            "focused_shortlist_v3"
        },
        source_sha256: input.source_sha256,
        budget_bytes: input.budget_bytes,
        payload_bytes: payload.len(),
        selected,
        candidates,
        relevant_candidates,
        truncated: selected < candidates,
        payload,
        graph,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(symbols: Vec<Symbol>, budget_bytes: usize) -> Input {
        Input {
            question: "How are cache receipts checked?".into(),
            source_sha256: "a".repeat(64),
            budget_bytes,
            symbols,
        }
    }

    fn graph_fixture() -> Vec<Symbol> {
        ["cache_receipts", "validate", "unconnected", "test_helper"]
            .into_iter()
            .enumerate()
            .map(|(index, name)| Symbol {
                file: "src/core.rs".into(),
                name: name.into(),
                kind: "function".into(),
                line: index as u32 + 1,
                signature: (name == "test_helper").then(|| "#[test] fn test_helper()".into()),
            })
            .collect()
    }

    #[test]
    fn graph_discovers_nonlexical_neighbors_without_promoting_disconnected_or_test_symbols() {
        let rows = graph_fixture();
        let graph = Graph {
            edges: vec![
                (Location::from(&rows[0]), Location::from(&rows[1])),
                (Location::from(&rows[0]), Location::from(&rows[3])),
            ],
            ..Graph::default()
        };
        let lexical = build(input(rows.clone(), 512)).unwrap();
        let ranked = build_graph(input(rows, 512), graph).unwrap();
        assert!(!lexical.payload.contains(":2 function validate"));
        assert!(ranked.payload.contains(":1 function cache_receipts"));
        assert!(ranked.payload.contains(":2 function validate"));
        assert!(!ranked.payload.contains("unconnected"));
        assert!(!ranked.payload.contains("test_helper"));
        assert!(ranked.payload_bytes <= 512);
        assert_eq!(ranked.graph.unwrap().usable_edges, 1);
    }

    #[test]
    fn graph_selection_is_independent_of_row_order_edge_direction_and_duplicate_references() {
        let rows = graph_fixture();
        let edge = (Location::from(&rows[0]), Location::from(&rows[1]));
        let expected = build_graph(
            input(rows.clone(), 1600),
            Graph {
                edges: vec![edge.clone()],
                ..Graph::default()
            },
        )
        .unwrap();
        let actual = build_graph(
            input(rows.into_iter().rev().collect(), 1600),
            Graph {
                edges: vec![(edge.1.clone(), edge.0.clone()), edge.clone(), edge],
                ..Graph::default()
            },
        )
        .unwrap();
        assert_eq!(actual.payload, expected.payload);
        assert_eq!(actual.graph.unwrap().usable_edges, 1);
    }

    #[test]
    fn missing_or_overflowed_graphs_preserve_lexical_payload_and_report_fallback() {
        for (graph, reason) in [
            (Graph::default(), "no_usable_edges"),
            (
                Graph {
                    overflow: true,
                    ..Graph::default()
                },
                "edge_limit",
            ),
        ] {
            let rows = graph_fixture();
            let expected = build(input(rows.clone(), 512)).unwrap();
            let result = build_graph(input(rows, 512), graph).unwrap();
            assert_eq!(result.payload, expected.payload);
            assert_eq!(result.graph.unwrap().fallback, Some(reason));
        }
        let mut no_seeds = input(graph_fixture(), 512);
        no_seeds.question = "unmatched phrase".into();
        let result = build_graph(no_seeds, Graph::default()).unwrap();
        assert_eq!(result.selected, 0);
        assert_eq!(result.graph.unwrap().fallback, Some("no_seeds"));
    }

    #[test]
    fn selection_is_query_relevant_stable_and_charged_in_utf8_bytes() {
        let symbols = vec![
            Symbol {
                file: "src/a.rs".into(),
                name: "unrelated".into(),
                kind: "fn".into(),
                line: 2,
                signature: None,
            },
            Symbol {
                file: "src/z.rs".into(),
                name: "cache_receipts_ключ".into(),
                kind: "fn".into(),
                line: 3,
                signature: Some("fn cache_receipts(ключ: String)".into()),
            },
        ];
        let result = build(input(symbols.clone(), 512)).unwrap();
        let reversed = build(input(symbols.into_iter().rev().collect(), 512)).unwrap();
        assert_eq!(result.payload, reversed.payload);
        assert!(result.payload.contains("src/z.rs"));
        assert!(!result.payload.contains("src/a.rs"));
        assert_eq!(result.selected, 1);
        assert_eq!(result.payload_bytes, result.payload.len());
        assert!(result.payload_bytes > result.payload.chars().count());
        assert!(result.payload_bytes <= 512);
        assert!(build(input(vec![], 511)).is_err());
    }

    #[test]
    fn omitted_symbols_and_invalid_locations_are_not_silent() {
        let row = Symbol {
            file: "src/a.rs".into(),
            name: "cache".repeat(200),
            kind: "fn".into(),
            line: 1,
            signature: None,
        };
        let result = build(input(vec![row.clone()], 512)).unwrap();
        assert_eq!(result.selected, 0);
        assert!(result.truncated);
        let invalid = Symbol {
            file: "../secret.rs".into(),
            ..row
        };
        assert!(build(input(vec![invalid], 512)).is_err());
    }

    #[test]
    fn task_subject_beats_generic_signature_hints_and_does_not_fill_spare_budget() {
        let symbols = vec![
            Symbol {
                file: "src/delivery_cache.rs".into(),
                name: "deliver".into(),
                kind: "method".into(),
                line: 123,
                signature: None,
            },
            Symbol {
                file: "src/helpers.rs".into(),
                name: "read_generic".into(),
                kind: "function".into(),
                line: 30,
                signature: Some("fn read_generic(cache: Cache, receipts: Receipt)".into()),
            },
            Symbol {
                file: "src/tests.rs".into(),
                name: "cache_receipts".into(),
                kind: "function".into(),
                line: 40,
                signature: Some("#[test] fn cache_receipts()".into()),
            },
        ];
        let result = build(input(symbols, 16000)).unwrap();
        assert!(result
            .payload
            .contains("src/delivery_cache.rs\n  :123 method deliver"));
        assert!(!result.payload.contains("helpers.rs"));
        assert!(!result.payload.contains("tests.rs"));
        assert_eq!(result.selected, 1);
        assert!(result.truncated);
    }

    #[test]
    fn ablations_preserve_locations_and_isolate_navigation_advice() {
        let symbols = vec![Symbol {
            file: "src/cache.rs".into(),
            name: "cache_receipts".into(),
            kind: "function".into(),
            line: 7,
            signature: None,
        }];
        let bundle = build(input(symbols.clone(), 512)).unwrap();
        let map = build(input(symbols.clone(), 512)).unwrap().map_only();
        let instructions = build(input(symbols, 512)).unwrap().instructions_only();
        assert_eq!(map.selected, bundle.selected);
        assert!(map
            .payload
            .contains("src/cache.rs\n  :7 function cache_receipts"));
        assert!(!map.payload.contains("Track ranges already read"));
        assert!(map.payload.contains("not behavioral evidence"));
        assert!(instructions.payload.contains("Track ranges already read"));
        assert!(!instructions.payload.contains("src/cache.rs"));
        assert_eq!(instructions.selected, 0);
        assert!(instructions.truncated);
        assert_eq!(
            bundle.payload_bytes,
            map.payload_bytes + instructions.payload_bytes
        );
        assert_eq!(map.payload_bytes, map.payload.len());
        assert_eq!(instructions.payload_bytes, instructions.payload.len());
    }
}
