cuda_tile.module @m {
  entry @staged_for(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12 = constant <i32: 128> : tile<i32>
    %13 = muli %9, %12 : tile<i32>
    %14 = constant <i32: 0> : tile<i32>
    %15 = constant <i32: 2> : tile<i32>
    %16 = constant <i32: 1> : tile<i32>
    %17, %18 = for %19 in (%14 to %15, step %16) : tile<i32> iter_values(%20 = %7, %21 = %0) -> (tile<128xf64>, token) {
      %22 = constant <i32: 0> : tile<i32>
      %23 = reshape %22 : tile<i32> -> tile<1xi32>
      %24 = broadcast %23 : tile<1xi32> -> tile<1xi32>
      %25 = iota : tile<1xi32>
      %26 = addi %24, %25 : tile<1xi32>
      %27 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %28 = broadcast %27 : tile<1xptr<f64>> -> tile<1xptr<f64>>
      %29 = offset %28, %26 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
      %30, %31 = load_ptr_tko weak %29 token=%0 : tile<1xptr<f64>> -> tile<1xf64>, token
      %32 = reduce %30 dim=0 identities=[0.0 : f64] : tile<1xf64> -> tile<f64> (%33: tile<f64>, %34: tile<f64>) {
        %35 = addf %33, %34 rounding<nearest_even> : tile<f64>
        yield %35 : tile<f64>
      }
      %36 = constant <f64: 0.0> : tile<f64>
      %37 = cmpf less_than ordered %32, %36 : tile<f64> -> tile<i1>
      %38, %39 = if %37 -> (tile<128xf64>, token) {
        %40 = constant <i32: 0> : tile<i32>
        %41, %42, %43 = get_tile_block_id : tile<i32>
        %44 = constant <i32: 1> : tile<i32>
        %45, %46 = for %47 in (%40 to %41, step %44) : tile<i32> iter_values(%48 = %20, %49 = %21) -> (tile<128xf64>, token) {
          %50 = addf %48, %7 rounding<nearest_even> : tile<128xf64>
          %51 = reshape %13 : tile<i32> -> tile<1xi32>
          %52 = broadcast %51 : tile<1xi32> -> tile<128xi32>
          %53 = iota : tile<128xi32>
          %54 = addi %52, %53 : tile<128xi32>
          %55 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
          %56 = broadcast %55 : tile<1xptr<f64>> -> tile<128xptr<f64>>
          %57 = offset %56, %54 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
          %58 = store_ptr_tko weak %57, %50 token=%49 : tile<128xptr<f64>>, tile<128xf64> -> token
          continue %50, %58 : tile<128xf64>, token
        }
        yield %45, %46 : tile<128xf64>, token
      } else {
        %59 = constant <i32: 0> : tile<i32>
        %60 = constant <i32: 2> : tile<i32>
        %61 = constant <i32: 1> : tile<i32>
        %62, %63 = for %64 in (%59 to %60, step %61) : tile<i32> iter_values(%65 = %20, %66 = %21) -> (tile<128xf64>, token) {
          %67 = subf %65, %7 rounding<nearest_even> : tile<128xf64>
          %68 = reshape %13 : tile<i32> -> tile<1xi32>
          %69 = broadcast %68 : tile<1xi32> -> tile<128xi32>
          %70 = iota : tile<128xi32>
          %71 = addi %69, %70 : tile<128xi32>
          %72 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
          %73 = broadcast %72 : tile<1xptr<f64>> -> tile<128xptr<f64>>
          %74 = offset %73, %71 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
          %75 = store_ptr_tko weak %74, %67 token=%66 : tile<128xptr<f64>>, tile<128xf64> -> token
          continue %67, %75 : tile<128xf64>, token
        }
        yield %62, %63 : tile<128xf64>, token
      }
      continue %38, %39 : tile<128xf64>, token
    }
    %76 = reshape %13 : tile<i32> -> tile<1xi32>
    %77 = broadcast %76 : tile<1xi32> -> tile<128xi32>
    %78 = iota : tile<128xi32>
    %79 = addi %77, %78 : tile<128xi32>
    %80 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %81 = broadcast %80 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %82 = offset %81, %79 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %83 = store_ptr_tko weak %82, %17 token=%18 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
