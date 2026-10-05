cuda_tile.module @m {
  entry @mha_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 4096> : tile<i32>
    %5 = muli %3, %4 : tile<i32>
    %6, %7, %8 = get_tile_block_id : tile<i32>
    %9 = constant <i32: 2048> : tile<i32>
    %10 = muli %6, %9 : tile<i32>
    %11 = addi %5, %10 : tile<i32>
    %12 = constant <f64: 0.0> : tile<32x32xf64>
    %13 = constant <i32: 0> : tile<i32>
    %14 = constant <i32: 2> : tile<i32>
    %15 = constant <i32: 1> : tile<i32>
    %16, %17 = for %18 in (%13 to %14, step %15) : tile<i32> iter_values(%19 = %12, %20 = %0) -> (tile<32x32xf64>, token) {
      %21 = constant <i32: 32> : tile<i32>
      %22 = muli %18, %21 : tile<i32>
      %23 = addi %11, %22 : tile<i32>
      %24 = reshape %23 : tile<i32> -> tile<1x1xi32>
      %25 = broadcast %24 : tile<1x1xi32> -> tile<32x32xi32>
      %26 = iota : tile<32xi32>
      %27 = reshape %26 : tile<32xi32> -> tile<32x1xi32>
      %28 = broadcast %27 : tile<32x1xi32> -> tile<32x32xi32>
      %29 = constant <i32: 64> : tile<32x32xi32>
      %30 = muli %28, %29 : tile<32x32xi32>
      %31 = addi %25, %30 : tile<32x32xi32>
      %32 = iota : tile<32xi32>
      %33 = reshape %32 : tile<32xi32> -> tile<1x32xi32>
      %34 = broadcast %33 : tile<1x32xi32> -> tile<32x32xi32>
      %35 = addi %31, %34 : tile<32x32xi32>
      %36 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %37 = broadcast %36 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %38 = offset %37, %35 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %39, %40 = load_ptr_tko weak %38 token=%20 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %41 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %42 = make_tensor_view %41, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
      %43 = make_partition_view %42 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %44, %45, %46 = get_tile_block_id : tile<i32>
      %47, %48 = load_view_tko weak %43[%18, %46] token=%40 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %49 = mmaf %39, %47, %19 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %49, %48 : tile<32x32xf64>, token
    }
    %50 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %51 = make_tensor_view %50, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %52 = make_partition_view %51 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %53, %54, %55 = get_tile_block_id : tile<i32>
    %56, %57, %58 = get_tile_block_id : tile<i32>
    %59 = store_view_tko weak %16, %52[%53, %58] token=%17 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
