cuda_tile.module @m {
  entry @count_eq(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = constant <i32: 1000> : tile<1024xi32>
    %11 = cmpi less_than %9, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <i32: 8> : tile<1024xi32>
    %13 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %14 = broadcast %13 : tile<1xptr<i32>> -> tile<1024xptr<i32>>
    %15 = offset %14, %9 : tile<1024xptr<i32>>, tile<1024xi32> -> tile<1024xptr<i32>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<1024xptr<i32>>, tile<1024xi1>, tile<1024xi32> -> tile<1024xi32>, token
    %18 = constant <i32: 7> : tile<1024xi32>
    %19 = cmpi equal %16, %18, signed : tile<1024xi32> -> tile<1024xi1>
    %20 = exti %19 unsigned : tile<1024xi1> -> tile<1024xi32>
    %21 = reduce %20 dim=0 identities=[0 : i32] : tile<1024xi32> -> tile<i32> (%22: tile<i32>, %23: tile<i32>) {
      %24 = addi %22, %23 : tile<i32>
      yield %24 : tile<i32>
    }
    %25 = constant <i32: 1> : tile<i32>
    %26 = muli %1, %25 : tile<i32>
    %27 = reshape %21 : tile<i32> -> tile<1xi32>
    %28 = broadcast %27 : tile<1xi32> -> tile<1xi32>
    %29 = reshape %26 : tile<i32> -> tile<1xi32>
    %30 = broadcast %29 : tile<1xi32> -> tile<1xi32>
    %31 = iota : tile<1xi32>
    %32 = addi %30, %31 : tile<1xi32>
    %33 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %34 = broadcast %33 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %35 = offset %34, %32 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %36 = store_ptr_tko weak %35, %28 token=%17 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
