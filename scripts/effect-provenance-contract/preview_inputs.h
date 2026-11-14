/* Source indices are immutable cache entries supplied by the source revision
 * loader. They contain parser coordinates, with no observation-derived data. */
static preview_source preview_inputs_load(const char *path) {
  FILE *f=fopen(path,"rb"); assert(f); assert(fseek(f,0,SEEK_END)==0);
  long len=ftell(f); assert(len>0 && fseek(f,0,SEEK_SET)==0);
  char *text=malloc((size_t)len+1); assert(text);
  assert(fread(text,1,(size_t)len,f)==(size_t)len && fclose(f)==0); text[len]=0;
  size_t lines=0; for(long i=0;i<len;i++) if(text[i]=='\n') lines++;
  preview_declaration *declarations=calloc(lines,sizeof(*declarations));
  preview_span *spans=calloc(lines,sizeof(*spans)); assert(declarations && spans);
  preview_source source={NULL,declarations,0,spans,0}; char *save=NULL;
  for(char *line=strtok_r(text,"\n",&save);line;line=strtok_r(NULL,"\n",&save)) {
    if(strncmp(line,"revision\t",9)==0) source.revision=line+9;
    else if(strncmp(line,"declaration\t",12)==0) {
      char *key=line+12,*a=strchr(key,'\t'); assert(a); *a++=0;
      char *b=strchr(a,'\t'); assert(b); *b++=0;
      declarations[source.declarations_n++]=(preview_declaration){key,strtoll(a,NULL,10),strtoll(b,NULL,10)};
    } else if(strncmp(line,"span\t",5)==0) {
      char *a=line+5,*b=strchr(a,'\t'); assert(b); *b++=0;
      spans[source.spans_n++]=(preview_span){strtoll(a,NULL,10),strtoll(b,NULL,10)};
    } else preview_require(0,"invalid source index entry");
  }
  preview_require(source.revision && source.declarations_n && source.spans_n,"incomplete source index");
  return source;
}
