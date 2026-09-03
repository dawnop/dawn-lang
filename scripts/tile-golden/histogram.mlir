cuda_tile.module @m {
  entry @histogram(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<64xi32>
    %8 = iota : tile<64xi32>
    %9 = addi %7, %8 : tile<64xi32>
    %10 = constant <i32: 500> : tile<64xi32>
    %11 = cmpi less_than %9, %10, signed : tile<64xi32> -> tile<64xi1>
    %12 = constant <i32: -1> : tile<64xi32>
    %13 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %14 = broadcast %13 : tile<1xptr<i32>> -> tile<64xptr<i32>>
    %15 = offset %14, %9 : tile<64xptr<i32>>, tile<64xi32> -> tile<64xptr<i32>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<64xptr<i32>>, tile<64xi1>, tile<64xi32> -> tile<64xi32>, token
    %18 = constant <i32: 0> : tile<64xi32>
    %19 = cmpi greater_than_or_equal %16, %18, signed : tile<64xi32> -> tile<64xi1>
    %20 = constant <i32: 16> : tile<64xi32>
    %21 = cmpi less_than %16, %20, signed : tile<64xi32> -> tile<64xi1>
    %22 = constant <i1: 0> : tile<64xi1>
    %23 = select %19, %21, %22 : tile<64xi1>, tile<64xi1>
    %24 = constant <i1: 0> : tile<64xi1>
    %25 = select %11, %23, %24 : tile<64xi1>, tile<64xi1>
    %26 = constant <i32: 15> : tile<64xi32>
    %27 = andi %16, %26 : tile<64xi32>
    %28 = constant <i32: 1> : tile<64xi32>
    %29 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %30 = broadcast %29 : tile<1xptr<i32>> -> tile<64xptr<i32>>
    %31 = offset %30, %27 : tile<64xptr<i32>>, tile<64xi32> -> tile<64xptr<i32>>
    %32, %33 = atomic_rmw_tko relaxed device %31, add, %28, %25 token=%17 : tile<64xptr<i32>>, tile<64xi32>, tile<64xi1> -> tile<64xi32>, token
    return
  }
}
