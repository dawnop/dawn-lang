cuda_tile.module @m {
  entry @transpose(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %8 = make_tensor_view %7, shape = [128, 64], strides = [64, 1] : tensor_view<128x64xf64, strides=[64, 1]>
    %9 = make_partition_view %8 : partition_view<tile=(32x32), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16, %17 = load_view_tko weak %9[%10, %14] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %18 = constant <i32: 4096> : tile<i32>
    %19 = muli %5, %18 : tile<i32>
    %20 = constant <i32: 32> : tile<i32>
    %21 = muli %1, %20 : tile<i32>
    %22 = addi %19, %21 : tile<i32>
    %23 = reshape %22 : tile<i32> -> tile<1x1xi32>
    %24 = broadcast %23 : tile<1x1xi32> -> tile<32x32xi32>
    %25 = iota : tile<32xi32>
    %26 = reshape %25 : tile<32xi32> -> tile<32x1xi32>
    %27 = broadcast %26 : tile<32x1xi32> -> tile<32x32xi32>
    %28 = addi %24, %27 : tile<32x32xi32>
    %29 = iota : tile<32xi32>
    %30 = reshape %29 : tile<32xi32> -> tile<1x32xi32>
    %31 = broadcast %30 : tile<1x32xi32> -> tile<32x32xi32>
    %32 = constant <i32: 128> : tile<32x32xi32>
    %33 = muli %31, %32 : tile<32x32xi32>
    %34 = addi %28, %33 : tile<32x32xi32>
    %35 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %36 = broadcast %35 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %37 = offset %36, %34 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %38 = store_ptr_tko weak %37, %16 token=%17 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
