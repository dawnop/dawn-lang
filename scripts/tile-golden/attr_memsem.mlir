cuda_tile.module @m {
  entry @attr_memsem(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 384> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %13 = broadcast %12 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %14 = offset %13, %11 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<i32>> -> tile<128xi32>, token
    %17 = reshape %7 : tile<i32> -> tile<1xi32>
    %18 = broadcast %17 : tile<1xi32> -> tile<128xi32>
    %19 = iota : tile<128xi32>
    %20 = addi %18, %19 : tile<128xi32>
    %21 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %22 = broadcast %21 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %23 = offset %22, %20 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %24, %25 = atomic_rmw_tko acquire tl_blk %23, add, %15 token=%16 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xi32>, token
    %26 = constant <i32: 128> : tile<128xi32>
    %27 = addi %20, %26 : tile<128xi32>
    %28 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %29 = broadcast %28 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %30 = offset %29, %27 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %31, %32 = atomic_rmw_tko release sys %30, add, %15 token=%25 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xi32>, token
    %33 = constant <i32: 256> : tile<128xi32>
    %34 = addi %20, %33 : tile<128xi32>
    %35 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %36 = broadcast %35 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %37 = offset %36, %34 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %38, %39 = atomic_rmw_tko acq_rel device %37, add, %15 token=%32 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xi32>, token
    return
  }
}
