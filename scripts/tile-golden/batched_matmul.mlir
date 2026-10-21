cuda_tile.module @m {
  entry @batched_matmul(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10 = constant <i32: 4096> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = constant <i32: 2048> : tile<i32>
    %13 = muli %1, %12 : tile<i32>
    %14 = addi %11, %13 : tile<i32>
    %15 = constant <i32: 4096> : tile<i32>
    %16 = muli %9, %15 : tile<i32>
    %17 = constant <i32: 32> : tile<i32>
    %18 = muli %5, %17 : tile<i32>
    %19 = addi %16, %18 : tile<i32>
    %20 = constant <f64: 0.0> : tile<32x32xf64>
    %21 = constant <i32: 0> : tile<i32>
    %22 = constant <i32: 2> : tile<i32>
    %23 = constant <i32: 1> : tile<i32>
    %24 = for %25 in (%21 to %22, step %23) : tile<i32> iter_values(%26 = %20) -> (tile<32x32xf64>) {
      %27 = constant <i32: 32> : tile<i32>
      %28 = muli %25, %27 : tile<i32>
      %29 = addi %14, %28 : tile<i32>
      %30 = reshape %29 : tile<i32> -> tile<1x1xi32>
      %31 = broadcast %30 : tile<1x1xi32> -> tile<32x32xi32>
      %32 = iota : tile<32xi32>
      %33 = reshape %32 : tile<32xi32> -> tile<32x1xi32>
      %34 = broadcast %33 : tile<32x1xi32> -> tile<32x32xi32>
      %35 = constant <i32: 64> : tile<32x32xi32>
      %36 = muli %34, %35 : tile<32x32xi32>
      %37 = addi %31, %36 : tile<32x32xi32>
      %38 = iota : tile<32xi32>
      %39 = reshape %38 : tile<32xi32> -> tile<1x32xi32>
      %40 = broadcast %39 : tile<1x32xi32> -> tile<32x32xi32>
      %41 = addi %37, %40 : tile<32x32xi32>
      %42 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %43 = broadcast %42 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %44 = offset %43, %41 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %45, %46 = load_ptr_tko weak %44 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %47 = constant <i32: 2048> : tile<i32>
      %48 = muli %25, %47 : tile<i32>
      %49 = addi %19, %48 : tile<i32>
      %50 = reshape %49 : tile<i32> -> tile<1x1xi32>
      %51 = broadcast %50 : tile<1x1xi32> -> tile<32x32xi32>
      %52 = iota : tile<32xi32>
      %53 = reshape %52 : tile<32xi32> -> tile<32x1xi32>
      %54 = broadcast %53 : tile<32x1xi32> -> tile<32x32xi32>
      %55 = constant <i32: 64> : tile<32x32xi32>
      %56 = muli %54, %55 : tile<32x32xi32>
      %57 = addi %51, %56 : tile<32x32xi32>
      %58 = iota : tile<32xi32>
      %59 = reshape %58 : tile<32xi32> -> tile<1x32xi32>
      %60 = broadcast %59 : tile<1x32xi32> -> tile<32x32xi32>
      %61 = addi %57, %60 : tile<32x32xi32>
      %62 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %63 = broadcast %62 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %64 = offset %63, %61 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %65, %66 = load_ptr_tko weak %64 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %67 = mmaf %45, %65, %26 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %67 : tile<32x32xf64>
    }
    %68 = reshape %24 : tile<32x32xf64> -> tile<1x32x32xf64>
    %69 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %70 = make_tensor_view %69, shape = [4, 64, 64], strides = [4096, 64, 1] : tensor_view<4x64x64xf64, strides=[4096, 64, 1]>
    %71 = make_partition_view %70 : partition_view<tile=(1x32x32), padding_value = zero, tensor_view<4x64x64xf64, strides=[4096, 64, 1]>, dim_map=[0, 1, 2]>
    %72, %73, %74 = get_tile_block_id : tile<i32>
    %75, %76, %77 = get_tile_block_id : tile<i32>
    %78, %79, %80 = get_tile_block_id : tile<i32>
    %81 = store_view_tko weak %68, %71[%74, %75, %79] token=%0 : tile<1x32x32xf64>, partition_view<tile=(1x32x32), padding_value = zero, tensor_view<4x64x64xf64, strides=[4096, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
