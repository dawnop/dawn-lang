/* A P1 preview owns a projected call tree and a row-to-owner index. Public
 * typed getters are the only provenance input. Source indices are cached by
 * revision; lazy Site materialization and matching stay inside consume(). */
import java.util.*;

final class PreviewConsumer {
  static final class SourceIndex {
    final String revision;
    final Map<String,long[]> declarations;
    final Set<Long> spans;
    SourceIndex(String revision, Map<String,long[]> declarations, Set<Long> spans) {
      this.revision=revision; this.declarations=declarations; this.spans=spans;
    }
    void match(String declaration, long lo, long hi, boolean syntax) {
      long[] extent=declarations.get(declaration);
      require(extent!=null && lo>=0 && hi>=lo && extent[0]+hi<=extent[1], "source declaration or range mismatch: "+declaration+" "+lo+".."+hi+" / "+Arrays.toString(extent));
      if(syntax) require(spans.contains(((extent[0]+lo)<<32)|(extent[0]+hi)), "source syntax mismatch");
    }
  }
  static final class Node {
    final std.provenance$InvocationKey key;
    final int parent;
    final std.provenance$CallState state;
    final std.provenance$Site site;
    final std.provenance$Definition definition;
    Node(std.provenance$InvocationKey key,std.provenance$CallState state,int parent,std.provenance$Site site,std.provenance$Definition definition) {
      this.key=key; this.parent=parent; this.state=state; this.site=site; this.definition=definition;
    }
  }
  static final class Mapping {
    final Node[] nodes; final int[] owners;
    Mapping(Node[] nodes,int[] owners) { this.nodes=nodes; this.owners=owners; }
  }
  static final class Cache {
    final Map<Long,std.provenance$Site> sites=new HashMap<>();
    final Map<Long,std.provenance$Definition> definitions=new HashMap<>();
  }
  static void require(boolean ok,String why) { if(!ok) throw new IllegalArgumentException(why); }
  static Object some(Option option) {
    require(option instanceof Option$Some,"missing public value"); return ((Option$Some)option).value;
  }
  static boolean userDefinition(std.provenance$Definition definition) {
    return definition!=null && definition.module.equals("main") && !definition.declaration.isEmpty();
  }
  static int slot(long value) {
    return std.provenance.index_present(value) ? Math.toIntExact(std.provenance.index_value(value)) : -1;
  }
  static int index(Option option) { return option instanceof Option$Some ? Math.toIntExact((Long)((Option$Some)option).value) : -1; }
  static Mapping consume(dawn.rt.Tuple3 snapshot,SourceIndex source,String artifactRevision,Cache cache) {
    require(source.revision.equals(artifactRevision),"source revision mismatch");
    std.provenance$SnapshotInfo info=std.provenance.snapshot_info(snapshot);
    require(info.completeness instanceof std.provenance$Completeness$Complete,"truncated provenance");
    dawn.rt.Tuple2 table=std.provenance.static_table(snapshot);
    dawn.rt.Tuple3 view=std.provenance.records(snapshot);
    require(std.provenance.record_scope(view)==info.scope && std.provenance.record_count(view)==info.records,"scope mismatch");
    int n=Math.toIntExact(info.records); int[] owners=new int[n];
    ArrayList<Node> nodes=new ArrayList<>();
    for(int row=0;row<n;row++) {
      require(std.provenance.record_boundary(view,row) instanceof std.provenance$Boundary$Known,"unknown boundary");
      std.provenance$CallState state=std.provenance.record_state(view,row);
      int parent=slot(std.provenance.record_parent(view,row)); require(parent>=-1 && parent<row,"invalid parent index");
      int owner=parent<0 ? -1 : owners[parent];
      int si=slot(std.provenance.record_site(view,row)),di=slot(std.provenance.record_definition(view,row));
      std.provenance$Site site=null; std.provenance$Definition definition=null;
      if(si>=0) {
        site=cache.sites.get((long)si);
        if(site==null) { site=(std.provenance$Site)some(std.provenance.site_at(table,si));
          if(site.module.equals("main")) {
            require(site.file.equals("main"),"source file mismatch");
            source.match(site.declaration,site.start,site.end,true);
            require(site.name_start==-1 && site.name_end==-1 || site.name_start>=site.start && site.name_end>=site.name_start && site.name_end<=site.end,"source name range mismatch");
          }
          cache.sites.put((long)si,site);
        }
      }
      if(di>=0) {
        definition=cache.definitions.get((long)di);
        if(definition==null) { definition=(std.provenance$Definition)some(std.provenance.definition_at(table,di));
          if(userDefinition(definition)) source.match(definition.declaration,definition.start,definition.end,false);
          else if(definition.module.equals("main")) require(definition.start==-1 && definition.end==-1 &&
              (definition.role.equals("primitive-slot") || definition.role.equals("derived-relation") || definition.role.equals("constructor-value")),"unknown synthetic definition");
          cache.definitions.put((long)di,definition);
        }
      }
      require(row==0 || site!=null || definition!=null,"unknown call identity");
      if(site!=null && site.module.equals("main") || userDefinition(definition)) {
        std.provenance$InvocationKey key=new std.provenance$InvocationKey(info.scope,std.provenance.record_epoch(view,row),std.provenance.record_instance(view,row));
        nodes.add(new Node(key,state,owner,site,definition)); owner=nodes.size()-1;
      }
      owners[row]=owner;
    }
    for(long i=0;i<info.notes;i++) {
      dawn.rt.Tuple4 origin=(dawn.rt.Tuple4)some(std.provenance.note_at(snapshot,i));
      require(std.provenance.origin_completeness(origin) instanceof std.provenance$Completeness$Complete,"truncated origin");
      require(std.provenance.origin_boundary(origin) instanceof std.provenance$Boundary$Known,"unknown origin boundary");
      std.provenance$InvocationKey key=new std.provenance$InvocationKey(std.provenance.scope(origin),std.provenance.epoch(origin),std.provenance.instance(origin));
      require(std.provenance.find_instance(snapshot,key) instanceof Option$Some,"uncommitted origin");
    }
    return new Mapping(nodes.toArray(new Node[0]),owners);
  }
}
