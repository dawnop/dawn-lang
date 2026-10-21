cuda_tile.module @m {
  entry @gqa_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 2> : tile<i32>
    %5 = muli %3, %4 : tile<i32>
    %6, %7, %8 = get_tile_block_id : tile<i32>
    %9 = addi %5, %6 : tile<i32>
    %10 = constant <i32: 4096> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = constant <f64: 0.0> : tile<64x32xf64>
    %13 = constant <i32: 0> : tile<i32>
    %14 = constant <i32: 2> : tile<i32>
    %15 = constant <i32: 1> : tile<i32>
    %16 = for %17 in (%13 to %14, step %15) : tile<i32> iter_values(%18 = %12) -> (tile<64x32xf64>) {
      %19 = constant <i32: 32> : tile<i32>
      %20 = muli %17, %19 : tile<i32>
      %21 = addi %11, %20 : tile<i32>
      %22 = reshape %21 : tile<i32> -> tile<1x1xi32>
      %23 = broadcast %22 : tile<1x1xi32> -> tile<64x32xi32>
      %24 = iota : tile<64xi32>
      %25 = reshape %24 : tile<64xi32> -> tile<64x1xi32>
      %26 = broadcast %25 : tile<64x1xi32> -> tile<64x32xi32>
      %27 = constant <i32: 64> : tile<64x32xi32>
      %28 = muli %26, %27 : tile<64x32xi32>
      %29 = addi %23, %28 : tile<64x32xi32>
      %30 = iota : tile<32xi32>
      %31 = reshape %30 : tile<32xi32> -> tile<1x32xi32>
      %32 = broadcast %31 : tile<1x32xi32> -> tile<64x32xi32>
      %33 = addi %29, %32 : tile<64x32xi32>
      %34 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %35 = broadcast %34 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
      %36 = offset %35, %33 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
      %37, %38 = load_ptr_tko weak %36 token=%0 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
      %39 = constant <i32: 2048> : tile<i32>
      %40 = muli %3, %39 : tile<i32>
      %41 = constant <i32: 1024> : tile<i32>
      %42 = muli %17, %41 : tile<i32>
      %43 = addi %40, %42 : tile<i32>
      %44 = reshape %43 : tile<i32> -> tile<1x1xi32>
      %45 = broadcast %44 : tile<1x1xi32> -> tile<32x32xi32>
      %46 = iota : tile<32xi32>
      %47 = reshape %46 : tile<32xi32> -> tile<32x1xi32>
      %48 = broadcast %47 : tile<32x1xi32> -> tile<32x32xi32>
      %49 = constant <i32: 32> : tile<32x32xi32>
      %50 = muli %48, %49 : tile<32x32xi32>
      %51 = addi %45, %50 : tile<32x32xi32>
      %52 = iota : tile<32xi32>
      %53 = reshape %52 : tile<32xi32> -> tile<1x32xi32>
      %54 = broadcast %53 : tile<1x32xi32> -> tile<32x32xi32>
      %55 = addi %51, %54 : tile<32x32xi32>
      %56 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %57 = broadcast %56 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %58 = offset %57, %55 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %59, %60 = load_ptr_tko weak %58 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %61 = mmaf %37, %59, %18 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %61 : tile<64x32xf64>
    }
    %62 = reshape %16 : tile<64x32xf64> -> tile<1x64x32xf64>
    %63 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %64 = make_tensor_view %63, shape = [2, 128, 32], strides = [4096, 32, 1] : tensor_view<2x128x32xf64, strides=[4096, 32, 1]>
    %65 = make_partition_view %64 : partition_view<tile=(1x64x32), padding_value = zero, tensor_view<2x128x32xf64, strides=[4096, 32, 1]>, dim_map=[0, 1, 2]>
    %66, %67, %68 = get_tile_block_id : tile<i32>
    %69, %70, %71 = get_tile_block_id : tile<i32>
    %72, %73, %74 = get_tile_block_id : tile<i32>
    %75 = store_view_tko weak %62, %65[%68, %69, %73] token=%0 : tile<1x64x32xf64>, partition_view<tile=(1x64x32), padding_value = zero, tensor_view<2x128x32xf64, strides=[4096, 32, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
