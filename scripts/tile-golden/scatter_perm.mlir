cuda_tile.module @m {
  entry @scatter_perm(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %11 = broadcast %10 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %12 = offset %11, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<128xptr<i32>> -> tile<128xi32>, token
    %15 = constant <i32: 0> : tile<128xi32>
    %16 = cmpi greater_than_or_equal %13, %15, signed : tile<128xi32> -> tile<128xi1>
    %17 = constant <i32: 256> : tile<128xi32>
    %18 = cmpi less_than %13, %17, signed : tile<128xi32> -> tile<128xi1>
    %19 = constant <i1: 0> : tile<128xi1>
    %20 = select %16, %18, %19 : tile<128xi1>, tile<128xi1>
    %21 = constant <i32: 255> : tile<128xi32>
    %22 = andi %13, %21 : tile<128xi32>
    %23 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %24 = broadcast %23 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %25 = offset %24, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %26, %27 = load_ptr_tko weak %25 token=%14 : tile<128xptr<f64>> -> tile<128xf64>, token
    %28 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %29 = broadcast %28 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %30 = offset %29, %22 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %31 = store_ptr_tko weak %30, %26, %20 token=%27 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
